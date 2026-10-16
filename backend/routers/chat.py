"""OpenAI-compatible chat; optional shared key stays in the server environment."""

from __future__ import annotations

import json
import os
import re
import httpx
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from auth import get_current_user_optional
import chat_limits
from sensenova_catalog import catalog, DEFAULT_MODEL

from schemas_chat import ChatIn, ChatOut

router = APIRouter(prefix="/api", tags=["chat"])


# Optional server-only shared key; user-supplied keys always take precedence.
DEFAULT_FREE_KEY = os.getenv('SENSENOVA_API_KEY', '').strip()


def resolve_api_key(provider: str, supplied: str | None) -> str:
    key = supplied.strip() if supplied else ''
    if not key and provider.lower() == 'sensenova':
        key = DEFAULT_FREE_KEY
    if not key:
        raise HTTPException(status_code=400, detail='请填写 API Key，或由管理员配置 SENSENOVA_API_KEY')
    return key

# 预设提供商 → 默认 Base URL（OpenAI 兼容 /v1）
PROVIDER_BASE_URLS: dict[str, str] = {
    "sensenova": "https://token.sensenova.cn/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "grok": "https://api.x.ai/v1",
    "openai": "https://api.openai.com/v1",
    "custom": "",  # 必须用户自填
}

DEFAULT_MODELS: dict[str, str] = {
    "sensenova": DEFAULT_MODEL,
    "deepseek": "deepseek-chat",
    "grok": "grok-2-latest",
    "openai": "gpt-4o-mini",
    "custom": "gpt-4o-mini",
}


def _resolve_base_url(provider: str, base_url: str | None) -> str:
    p = (provider or "sensenova").lower().strip()
    if base_url:
        url = base_url.rstrip("/")
        # 允许用户填 http://127.0.0.1:3000 或 .../v1
        if not url.endswith("/v1"):
            url = url + "/v1"
        return url
    if p == "custom":
        raise HTTPException(status_code=400, detail="自定义提供商必须填写 Base URL")
    default = PROVIDER_BASE_URLS.get(p)
    if not default:
        raise HTTPException(
            status_code=400,
            detail=f"未知提供商: {provider}，可选 sensenova / deepseek / grok / openai / custom",
        )
    return default


@router.get("/chat/providers")
async def list_providers():
    """前端下拉菜单用的预设列表。"""
    models, source = await catalog(DEFAULT_FREE_KEY)
    return {
        "providers": [
            {
                "id": "sensenova",
                "name": "商汤日日新 (SenseNova)",
                "base_url": PROVIDER_BASE_URLS["sensenova"],
                "models": models,
                "default_model": DEFAULT_MODEL if DEFAULT_MODEL in models else (models[0] if models else ''),
                "catalog_source": source,
                "requires_login": True,
                "site_key_configured": bool(DEFAULT_FREE_KEY),
                "is_free": bool(DEFAULT_FREE_KEY),
            },

            {
                "id": "deepseek",
                "name": "DeepSeek",
                "base_url": PROVIDER_BASE_URLS["deepseek"],
                "models": ["deepseek-chat", "deepseek-reasoner"],
            },


            {
                "id": "grok",
                "name": "Grok (xAI)",
                "base_url": PROVIDER_BASE_URLS["grok"],
                "models": ["grok-2-latest", "grok-beta"],
            },
            {
                "id": "openai",
                "name": "OpenAI",
                "base_url": PROVIDER_BASE_URLS["openai"],
                "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini"],
            },
            {
                "id": "custom",
                "name": "自定义 (OpenAI 兼容)",
                "base_url": "",
                "models": [],
                "hint": "例如本地 http://127.0.0.1:3000 或 OneAPI 网关",
            },
        ]
    }


async def prepare(data, user):
    provider = data.provider.lower().strip()
    base = _resolve_base_url(provider, data.base_url)
    key = resolve_api_key(provider, data.api_key)
    shared = provider == 'sensenova' and not (data.api_key or '').strip()
    if shared:
        if base != PROVIDER_BASE_URLS['sensenova']:
            raise HTTPException(400, '站点密钥仅用于官方商汤地址')
        if user is None:
            raise HTTPException(401, '请先登录博客，或填写自己的 API Key')
        if sum(len(m.content) for m in data.messages) > 40000:
            raise HTTPException(400, '对话过长，请开启新对话后重试')
    model = data.model or DEFAULT_MODELS.get(provider, 'gpt-4o-mini')
    if provider == 'sensenova':
        models, _ = await catalog(DEFAULT_FREE_KEY)
        if not data.model or model in ('Nova-5-Pro', 'sensenova-6.7-flash-lite'):
            model = DEFAULT_MODEL if DEFAULT_MODEL in models else (models[0] if models else '')
        if shared and model not in models:
            raise HTTPException(400, '该模型未开放站点调用，请刷新模型列表或选择其他模型')
    if not model:
        raise HTTPException(503, '暂时没有可用文本模型，请稍后重试')
    payload = {'model': model, 'messages': [m.model_dump() for m in data.messages]}
    if provider == 'sensenova':
        # Official Kimi K3 fixes temperature at 1 and uses a different token field.
        limit_field = 'max_completion_tokens' if model.startswith('kimi-') else 'max_tokens'
        payload[limit_field] = min(data.max_tokens, 4096) if shared else data.max_tokens
        payload['reasoning_effort'] = data.reasoning_effort
        if model.startswith('sensenova-'):
            payload['temperature'] = data.temperature
    else:
        payload.update(temperature=data.temperature, max_tokens=data.max_tokens)
    return base + '/chat/completions', payload, key, (user.id if shared else None)


def upstream_error(status, body, key):
    if status == 429:
        return '模型平台额度或调用频率已达限制，请稍后重试或选择其他模型（429）'
    if status == 401:
        return '模型平台鉴权失败，请检查 API Key（401）'
    if status == 403:
        return '当前模型未在此 Key 的套餐中开通，请选择其他模型（403）'
    if status == 404:
        return '模型或接口已更新，请刷新页面选择最新模型（404）'
    text = str(body).replace(key, '[redacted]')
    text = re.sub(r'sk-[A-Za-z0-9_-]+', '[redacted]', text)
    try:
        parsed = json.loads(text)
        text = (parsed.get('error') or {}).get('message') or parsed.get('message') or text
    except (ValueError, AttributeError, TypeError):
        pass
    return f'模型服务返回错误（{status}）：{str(text)[:250]}'


@router.post('/chat', response_model=ChatOut)
async def chat(data: ChatIn, user=Depends(get_current_user_optional)):
    url, payload, key, shared_user = await prepare(data, user)
    lease = chat_limits.reserve(shared_user) if shared_user is not None else None
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(120, connect=15)) as client:
            response = await client.post(url, json={**payload, 'stream': False},
                headers={'Authorization': f'Bearer {key}'})
        if response.status_code >= 400:
            status = response.status_code if response.status_code in (401, 403, 429) else (400 if response.status_code < 500 else 502)
            raise HTTPException(status, upstream_error(response.status_code, response.text, key))
        body = response.json()
        choice = body['choices'][0]
        reply = (choice.get('message') or {}).get('content') or choice.get('text') or ''
        if not str(reply).strip():
            raise HTTPException(502, '模型未返回正文，请缩短问题或切换快速回答模式')
        return ChatOut(reply=str(reply), model=body.get('model') or payload['model'],
                       provider=data.provider, usage=body.get('usage') if isinstance(body.get('usage'), dict) else None)
    except httpx.TimeoutException:
        raise HTTPException(504, '模型响应超时，请稍后重试') from None
    except httpx.HTTPError:
        raise HTTPException(502, '模型服务连接异常，请稍后重试') from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise HTTPException(502, '模型响应格式异常，请稍后重试') from None
    finally:
        if lease is not None:
            chat_limits.release(shared_user, lease)


def event(value):
    return f'data: {json.dumps(value, ensure_ascii=False)}\n\n'


@router.post('/chat/stream')
async def chat_stream(data: ChatIn, user=Depends(get_current_user_optional)):
    url, payload, key, shared_user = await prepare(data, user)
    lease = chat_limits.reserve(shared_user) if shared_user is not None else None

    def release_lease():
        if lease is not None:
            chat_limits.release(shared_user, lease)

    async def event_generator():
        received = False
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(120, connect=15)) as client:
                async with client.stream('POST', url, json={**payload, 'stream': True},
                                         headers={'Authorization': f'Bearer {key}'}) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        yield event({'error': upstream_error(response.status_code, body.decode('utf-8', errors='ignore'), key)})
                        return
                    yield event({'model': payload['model']})
                    async for line in response.aiter_lines():
                        if not line.startswith('data:'):
                            continue
                        raw = line[5:].strip()
                        if raw == '[DONE]':
                            break
                        try:
                            chunk = json.loads(raw)
                            if chunk.get('error'):
                                yield event({'error': upstream_error(502, raw, key)})
                                return
                            choices = chunk.get('choices') or []
                            delta = choices[0].get('delta') or {} if choices else {}
                            content = delta.get('content') or delta.get('text')
                            if isinstance(content, str) and content:
                                received = True
                                yield event({'content': content})
                        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                            continue
                    if not received:
                        yield event({'error': '模型未返回正文，请缩短问题或切换快速回答模式'})
                    yield 'data: [DONE]\n\n'
        except httpx.TimeoutException:
            yield event({'error': '模型响应超时，请稍后重试'})
        except httpx.HTTPError:
            yield event({'error': '模型服务连接异常，请稍后重试'})
        finally:
            release_lease()

    return StreamingResponse(event_generator(), media_type='text/event-stream',
        headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-store'},
        background=BackgroundTask(release_lease))


