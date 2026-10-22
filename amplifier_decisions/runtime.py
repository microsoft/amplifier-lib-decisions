"""Optional duck-typed lifecycle, policy and receipts. No Core dependency."""
import asyncio
import time

from .contracts import Answer, DecisionResult


class DecisionFailure(Exception):
    """A redacted local outcome; never a provider response or credential."""
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


class SystemOneBackend:
    def __init__(self, provider, model, send, *, coordinator=None, checkpoint=None, cost=None, capabilities=None):
        from .systemone import SystemOneCodec
        self.provider, self.model, self.send = provider, model, send
        self.codec = SystemOneCodec(model)
        if capabilities is not None:
            self.codec.capabilities = capabilities
        self.capabilities = self.codec.capabilities
        self.coordinator, self.closed = coordinator, False
        self.checkpoint, self.cost = checkpoint, dict(cost or {})

    async def decide(self, request):
        start = time.monotonic()
        def result(answers, payload=None, request_id=None):
            payload = payload or {}
            raw = payload.get('usage', {})
            usage = {k: v for k, v in raw.items() if k in {'input_tokens', 'output_tokens', 'total_tokens'}
                     and type(v) is int and v >= 0} if isinstance(raw, dict) else {}
            model = payload.get('model')
            return DecisionResult(self.provider, self.model, model if isinstance(model, str) else None,
                                  answers, round((time.monotonic()-start)*1000, 3), usage, request_id,
                                  self.checkpoint if payload else None, dict(self.cost))
        def fail(status, reason):
            return result({q.name: Answer(q.name, q.kind, status, reason=reason) for q in request.questions})
        if self.closed:
            return fail('unavailable', 'closed')
        try:
            content = self.codec._body(request)
        except (ValueError, TypeError, RecursionError):
            return fail('invalid', 'invalid_or_unsupported_request')
        if self.coordinator:
            check = await self.coordinator.hooks.emit('decision:request', {
                'provider': self.provider, 'model': self.model, 'questions': len(request.questions)})
            check = await self.coordinator.process_hook_result(check, 'decision:request', self.provider)
            if check.action == 'deny':
                return fail('unavailable', 'host_denied')
        try:
            async with asyncio.timeout(request.timeout_seconds):
                payload, request_id = await self.send(content, request.timeout_seconds)
            if not isinstance(payload, dict):
                raise DecisionFailure('invalid', 'response_shape')
            rows = payload.get('answers')
            if not isinstance(rows, dict) or set(rows) - {q.name for q in request.questions}:
                raise DecisionFailure('invalid', 'answer_envelope')
            value = result({q.name: self.codec._answer(q, rows.get(q.name)) for q in request.questions}, payload, request_id)
        except TimeoutError:
            value = fail('unavailable', 'timeout')
        except DecisionFailure as exc:
            value = fail(exc.status, exc.reason)
        except (ValueError, TypeError, RecursionError):
            value = fail('invalid', 'response_shape')
        if self.coordinator:
            await self.coordinator.hooks.emit('decision:response', {
                'provider': self.provider, 'model': value.reported_model,
                'usage': value.usage, 'request_id': value.request_id, 'elapsed_ms': value.elapsed_ms,
                'statuses': {k: v.status for k, v in value.answers.items()},
                'checkpoint': value.checkpoint, 'cost': value.cost})
        return value

    async def close(self):
        self.closed = True


def register(coordinator, identity, backend):
    """Register one named backend. Caller owns closing its account transport."""
    current = dict(coordinator.get_capability('decision.backends') or {})
    if not isinstance(identity, str) or not identity or identity in current:
        raise ValueError('Decision backend identifiers must be unique')
    current[identity] = backend
    coordinator.register_capability('decision.backends', current)
    if hasattr(coordinator, 'register_contributor'):
        coordinator.register_contributor('observability.events', identity,
                                         lambda: ['decision:request', 'decision:response'])
    async def cleanup():
        current = dict(coordinator.get_capability('decision.backends') or {})
        if current.get(identity) is backend:
            del current[identity]
            coordinator.register_capability('decision.backends', current)
        await backend.close()
    return cleanup
