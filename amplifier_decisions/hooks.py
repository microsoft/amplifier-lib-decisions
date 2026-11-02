"""Account-owned decision hook lifecycle, independent of any application or Core.

Hosts may project an authorized saved account into a hook configuration. The
reserved ``_decision_account`` envelope is a correlation receipt, not authority
to read credentials. Credentials must already have been resolved by the host.
"""
import asyncio

from .config import configured_backends
from .runtime import register


class UnsafeAccountCleanup(RuntimeError):
    """A factory could not release resources allocated before it returned.

    Factories own partial construction: close those resources before raising a
    normal failure, or raise this signal if cleanup cannot be completed. A host
    must not accept ordinary fallback from an account in this state.
    """


async def mount_account(coordinator, config, *, provider_factory, default_id, hook_module):
    """Mount an optional account through Core's supported hook lifecycle.

No callback is needed for a directly configured hook. A projecting host installs
``decision.account_lifecycle(binding_id, hook_module, outcome, error=None)`` and
must verify every expected receipt before execution. Only literal True for
``unavailable`` accepts ordinary fallback after complete rollback. A callback
error, cancellation, or incomplete rollback always raises. Errors are passed only
to that private callback; they must not be rendered without host redaction.
"""
    config = config or {}
    binding = config.get('_decision_account') or {}
    callback = coordinator.get_capability('decision.account_lifecycle')
    binding_id = binding.get('binding_id') if isinstance(binding, dict) else None

    async def report(outcome, error=None):
        if callback is not None and binding_id:
            return await callback(binding_id, hook_module, outcome, error)
        return None

    provider = None
    removals = []
    attempted = []
    owned = []
    cleanup_task = None

    async def release_all():
        errors = []
        # Attempt every release even when another fails. Never take another
        # account's identity or replacement backend away during rollback.
        for release in reversed(removals):
            try:
                await release()
            except BaseException as exc:
                errors.append(exc)
        for backend in attempted:
            try:
                await backend.close()
            except BaseException as exc:
                errors.append(exc)
        if provider is not None:
            try:
                await provider.close()
            except BaseException as exc:
                errors.append(exc)
        try:
            current = coordinator.get_capability('decision.backends') or {}
            if any(current.get(identity) is backend for identity, backend in owned):
                errors.append(RuntimeError('Decision account rollback left an owned registration'))
        except BaseException as exc:
            errors.append(exc)
        return errors

    async def settle():
        # A second cancel must not detach unfinished cleanup. The caller still
        # observes cancellation after all releases have been attempted.
        nonlocal cleanup_task
        if cleanup_task is None:
            cleanup_task = asyncio.create_task(release_all())
        interrupted = None
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError as exc:
                interrupted = exc
        return cleanup_task.result(), interrupted

    async def cleanup():
        errors, interrupted = await settle()
        if errors:
            error = BaseExceptionGroup('Decision account cleanup failed', errors)
            await report('unsafe', error)
            raise error
        if interrupted is not None:
            raise interrupted

    notifying = False
    try:
        rows = configured_backends(config, default_id)
        if not rows:
            notifying = True
            await report('disabled')
            return None
        provider = provider_factory(config=config)
        for identity, row in rows.items():
            backend = provider.decision_backend(row, coordinator)
            owned.append((identity, backend))
            attempted.append(backend)
            removals.append(register(coordinator, identity, backend))
            attempted.pop()  # A successful registration owns backend closure.
        notifying = True
        await report('ready')
        return cleanup
    except BaseException as error:
        errors, interrupted = await settle()
        if errors:
            failure = BaseExceptionGroup('Decision account rollback failed', [error, *errors])
            await report('unsafe', failure)
            raise failure
        if isinstance(error, asyncio.CancelledError) or interrupted is not None:
            try:
                await report('cancelled', error)
            finally:
                raise interrupted if interrupted is not None else error
        if notifying or isinstance(error, UnsafeAccountCleanup) or not isinstance(error, Exception):
            await report('unsafe', error)
            raise
        if await report('unavailable', error) is True:
            return None
        raise
