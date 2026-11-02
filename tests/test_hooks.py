"""Account mounting is transactional; a host cannot accept unsafe fallback."""
import asyncio

import pytest

from amplifier_decisions.hooks import UnsafeAccountCleanup, mount_account


class Backend:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class Account:
    def __init__(self, config):
        self.backends = []
        self.closed = False

    def decision_backend(self, row, coordinator):
        backend = Backend()
        self.backends.append(backend)
        return backend

    async def close(self):
        self.closed = True


class Coordinator:
    def __init__(self, callback=None):
        self.caps = {'decision.account_lifecycle': callback}
        self.contributor = lambda *args: None

    def get_capability(self, name):
        return self.caps.get(name)

    def register_capability(self, name, value):
        self.caps[name] = value

    def register_contributor(self, *args):
        self.contributor(*args)


def config(*identities, enabled=True):
    return {'_decision_account': {'binding_id': 'opaque'}, 'decisions': {
        'enabled': enabled, 'backends': {identity: {'enabled': True} for identity in identities}}}


async def mount(coordinator, value, accounts):
    def factory(config):
        account = Account(config)
        accounts.append(account)
        return account
    return await mount_account(coordinator, value, provider_factory=factory,
                               default_id='default', hook_module='hooks-example-decisions')


async def test_success_and_disabled_have_explicit_receipts_and_owned_cleanup():
    receipts, accounts = [], []

    async def report(*args):
        receipts.append(args[:3])

    coordinator = Coordinator(report)
    assert await mount(coordinator, config('unused', enabled=False), accounts) is None
    assert not accounts and receipts[-1][-1] == 'disabled'
    cleanup = await mount(coordinator, config('first', 'second'), accounts)
    assert receipts[-1] == ('opaque', 'hooks-example-decisions', 'ready')
    replacement = Backend()
    coordinator.caps['decision.backends']['first'] = replacement
    await cleanup()
    await cleanup()  # Repeated teardown does not reopen or reclaim another account.
    assert coordinator.caps['decision.backends'] == {'first': replacement}
    assert accounts[0].closed and all(backend.closed for backend in accounts[0].backends)
    assert not replacement.closed


@pytest.mark.parametrize('error_type', [RuntimeError, asyncio.CancelledError])
async def test_partial_registration_failure_closes_attempted_and_registered_backends(error_type):
    accounts, receipts = [], []
    coordinator = Coordinator()
    other = Backend()
    coordinator.caps['decision.backends'] = {'other-account': other}
    error = error_type('synthetic contributor fault')

    def fail(channel, identity, callback):
        if identity == 'second':
            raise error

    async def report(binding, module, outcome, cause):
        receipts.append(outcome)
        return True  # Acceptance must never swallow cancellation.

    coordinator.contributor = fail
    coordinator.caps['decision.account_lifecycle'] = report
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await mount(coordinator, config('first', 'second'), accounts)
        assert receipts == ['cancelled']
    else:
        assert await mount(coordinator, config('first', 'second'), accounts) is None
        assert receipts == ['unavailable']
    assert coordinator.caps['decision.backends'] == {'other-account': other}
    assert accounts[0].closed and all(backend.closed for backend in accounts[0].backends)
    assert not other.closed


@pytest.mark.parametrize('accept', [None, False, 1])
async def test_failure_needs_explicit_true_from_host_to_allow_fallback(accept):
    accounts = []

    async def report(*args):
        return accept

    coordinator = Coordinator(report if accept is not None else None)
    coordinator.caps['decision.backends'] = {'duplicate': Backend()}
    with pytest.raises(ValueError, match='unique'):
        await mount(coordinator, config('first', 'duplicate'), accounts)
    assert list(coordinator.caps['decision.backends']) == ['duplicate']
    assert accounts[0].closed and all(backend.closed for backend in accounts[0].backends)


async def test_callback_failure_unwinds_and_cannot_be_accepted_as_unavailable():
    accounts, receipts = [], []

    async def report(binding, module, outcome, cause):
        receipts.append(outcome)
        if outcome == 'ready':
            raise RuntimeError('receipt rejected')
        return True

    coordinator = Coordinator(report)
    with pytest.raises(RuntimeError, match='receipt rejected'):
        await mount(coordinator, config('first'), accounts)
    assert receipts == ['ready', 'unsafe']
    assert not coordinator.caps['decision.backends']
    assert accounts[0].closed and accounts[0].backends[0].closed


async def test_second_cancel_waits_for_cleanup_and_preserves_cancellation():
    accounts, receipts = [], []
    ready, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_close = Account.close

    async def report(binding, module, outcome, cause):
        receipts.append(outcome)
        if outcome == 'ready':
            ready.set()
            await asyncio.Event().wait()

    class SlowAccount(Account):
        async def close(self):
            closing.set()
            await release.wait()
            await original_close(self)

    def factory(config):
        account = SlowAccount(config)
        accounts.append(account)
        return account

    coordinator = Coordinator(report)
    task = asyncio.create_task(mount_account(coordinator, config('first'),
        provider_factory=factory, default_id='default', hook_module='hooks-example-decisions'))
    await ready.wait()
    task.cancel()
    await closing.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert receipts == ['ready', 'cancelled']
    assert not coordinator.caps['decision.backends'] and accounts[0].closed


async def test_failed_withdrawal_closes_backend_and_account_but_is_unsafe():
    accounts, receipts = [], []
    coordinator = Coordinator()

    async def report(binding, module, outcome, cause):
        receipts.append(outcome)
        return True

    coordinator.caps['decision.account_lifecycle'] = report
    cleanup = await mount(coordinator, config('first'), accounts)

    def fail(*args):
        raise RuntimeError('registry withdrawal failed')

    coordinator.register_capability = fail
    with pytest.raises(BaseExceptionGroup, match='cleanup failed'):
        await cleanup()
    assert receipts == ['ready', 'unsafe']
    assert accounts[0].closed and accounts[0].backends[0].closed


@pytest.mark.parametrize('error_type', [RuntimeError, UnsafeAccountCleanup])
async def test_factory_partial_construction_must_report_incomplete_cleanup(error_type):
    receipts = []
    error = error_type('synthetic factory failure')

    def factory(config):
        # An account not returned by the factory cannot be unwound by mount.
        raise error

    async def report(binding, module, outcome, cause):
        assert cause is error
        receipts.append(outcome)
        return True

    coordinator = Coordinator(report)
    arguments = dict(provider_factory=factory, default_id='default', hook_module='hooks-example-decisions')
    if error_type is UnsafeAccountCleanup:
        with pytest.raises(UnsafeAccountCleanup) as caught:
            await mount_account(coordinator, config('first'), **arguments)
        assert caught.value is error and receipts == ['unsafe']
    else:
        assert await mount_account(coordinator, config('first'), **arguments) is None
        assert receipts == ['unavailable']
    assert not coordinator.get_capability('decision.backends')
