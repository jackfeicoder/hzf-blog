"""Five-minute, single-flight official text-model catalog. No key is returned."""
import asyncio
from decimal import Decimal, InvalidOperation
import time
import httpx

DEFAULT_MODEL = 'sensenova-6.8-flash-lite'
FALLBACK_MODELS = [DEFAULT_MODEL, 'deepseek-v4-flash', 'kimi-k3']
_state = {'models': list(FALLBACK_MODELS), 'next_refresh': 0, 'source': 'fallback'}
_lock = asyncio.Lock()


def text_models(rows):
    ids = []
    for row in rows:
        if not isinstance(row, dict) or 'text' not in row.get('output_modalities', []):
            continue
        model = row.get('id')
        if not isinstance(model, str) or not model or len(model) > 120:
            continue
        # Only the owner's selected/previously used models are offered. New
        # entries in the upstream catalog do not silently become site models.
        if model not in FALLBACK_MODELS:
            continue
        # The current token plan rejects this internal ID; official docs use
        # deepseek-flash for V4.1. Do not offer the rejected alias to users.
        if model == 'deepseek-v4.1-flash':
            continue
        pricing = row.get('pricing') or {}
        try:
            if not pricing or any(Decimal(str(price)) != 0 for price in pricing.values()):
                continue
        except (InvalidOperation, TypeError, ValueError):
            continue
        if model not in ids:
            ids.append(model)
    return sorted(ids, key=lambda model: (model != DEFAULT_MODEL,
                  FALLBACK_MODELS.index(model) if model in FALLBACK_MODELS else len(FALLBACK_MODELS), model))


async def catalog(key):
    if not key:
        return list(FALLBACK_MODELS), 'fallback'
    if time.monotonic() < _state['next_refresh']:
        return list(_state['models']), _state['source']
    async with _lock:
        if time.monotonic() < _state['next_refresh']:
            return list(_state['models']), _state['source']
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
                response = await client.get('https://token.sensenova.cn/v1/models',
                    headers={'Authorization': f'Bearer {key}'})
                response.raise_for_status()
                rows = response.json()['data']
                if not isinstance(rows, list):
                    raise ValueError('Invalid catalog')
                _state.update(models=text_models(rows), source='official', next_refresh=time.monotonic() + 300)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            # Keep the last known list; suppress repeated network attempts.
            _state.update(source='cached' if _state['source'] != 'fallback' else 'fallback',
                          next_refresh=time.monotonic() + 60)
        return list(_state['models']), _state['source']
