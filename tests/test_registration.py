"""Registration failure must not leave an executable decision backend behind."""
import asyncio

import pytest

from amplifier_decisions.runtime import register


class Backend:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class Coordinator:
    def __init__(self, backends=None, contributor=None):
        self.backends = dict(backends or {})
        self.contributor = contributor

    def get_capability(self, name):
        assert name == 'decision.backends'
        return self.backends

    def register_capability(self, name, value):
        assert name == 'decision.backends'
        self.backends = value

    def register_contributor(self, channel, name, callback):
        assert channel == 'observability.events'
        assert callback() == ['decision:request', 'decision:response']
        if self.contributor:
            self.contributor(self, name)


@pytest.mark.parametrize('error_type', [RuntimeError, asyncio.CancelledError])
def test_contributor_failure_removes_only_new_backend(error_type):
    existing, added, failed = Backend(), Backend(), Backend()
    error = error_type('Synthetic contributor failure')

    def fail(coordinator, identity):
        coordinator.backends['other-new'] = added
        raise error

    coordinator = Coordinator({'existing': existing}, contributor=fail)
    with pytest.raises(error_type) as caught:
        register(coordinator, 'failed', failed)

    assert caught.value is error
    assert coordinator.backends == {'existing': existing, 'other-new': added}
    assert not existing.closed and not added.closed and not failed.closed


def test_contributor_failure_preserves_replacement_backend():
    replacement = Backend()

    def fail(coordinator, identity):
        coordinator.backends[identity] = replacement
        raise RuntimeError('Synthetic contributor failure')

    coordinator = Coordinator(contributor=fail)
    with pytest.raises(RuntimeError):
        register(coordinator, 'replaced', Backend())
    assert coordinator.backends == {'replaced': replacement}
    assert not replacement.closed


def test_duplicate_identity_does_not_change_or_close_existing_backend():
    original = Backend()
    coordinator = Coordinator({'same': original})
    with pytest.raises(ValueError, match='unique'):
        register(coordinator, 'same', Backend())
    assert coordinator.backends == {'same': original}
    assert not original.closed


async def test_successful_cleanup_closes_only_its_backend_and_keeps_replacement():
    owned, replacement, other = Backend(), Backend(), Backend()
    coordinator = Coordinator({'other': other})
    cleanup = register(coordinator, 'selected', owned)
    assert coordinator.backends == {'other': other, 'selected': owned}
    coordinator.backends['selected'] = replacement
    await cleanup()
    assert coordinator.backends == {'other': other, 'selected': replacement}
    assert owned.closed and not replacement.closed and not other.closed
