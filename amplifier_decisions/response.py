"""Bounded response parsing; transport and account stay with the provider."""
import json
from .runtime import DecisionFailure


async def read_json(response):
    if response.status_code != 200:
        raise DecisionFailure('invalid' if response.status_code in {400, 413, 415, 422} else 'unavailable',
                              f'http_{response.status_code}')
    chunks, size = [], 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > 4 * 1024**2:
            raise DecisionFailure('invalid', 'response_limit')
        chunks.append(chunk)
    return json.loads(b''.join(chunks)), response.headers.get('x-request-id') or response.headers.get('apim-request-id')
