"""OpenAI 兼容聊天代理。API Key 由用户前端传入，服务端不存储。"""

from __future__ import annotations

import json
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from schemas_chat import ChatIn, ChatOut

router = APIRouter(prefix="/api", tags=["chat"])


# 默认全员免费 API Key (商汤 SenseNova)
DEFAULT_FREE_KEY = "sk-lQYXt2cgWUprdhd4zksTF3FH9FrEOC2H"

# 预设提供商 → 默认 Base URL（OpenAI 兼容 /v1）
PROVIDER_BASE_URLS: dict[str, str] = {
    "sensenova": "https://token.sensenova.cn/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "grok": "https://api.x.ai/v1",
    "openai": "https://api.openai.com/v1",
    "custom": "",  # 必须用户自填
}

DEFAULT_MODELS: dict[str, str] = {
    "sensenova": "sensenova-6.7-flash-lite",
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
def list_providers():
    """前端下拉菜单用的预设列表。"""
    return {
        "providers": [
            {
                "id": "sensenova",
                "name": "商汤日日新 (SenseNova · 默认免费)",
                "base_url": PROVIDER_BASE_URLS["sensenova"],
                "models": ["sensenova-6.7-flash-lite", "deepseek-v4-flash"],
                "is_free": True,
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


@router.post("/chat", response_model=ChatOut)
async def chat(data: ChatIn):
    base = _resolve_base_url(data.provider, data.base_url)
    model = data.model or DEFAULT_MODELS.get(data.provider.lower(), "Nova-5-Pro")
    url = f"{base}/chat/completions"

    # API Key 降级策略：如果是 SenseNova 且未传有效 Key，强制自动填充免费公用 Key
    api_key = data.api_key.strip() if data.api_key else ""
    if data.provider.lower() == "sensenova":
        if not api_key or not api_key.startswith("sk-lQYXt"):
            api_key = DEFAULT_FREE_KEY
    elif not api_key:
        raise HTTPException(status_code=400, detail="请填写该模型提供商的 API Key")



    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in data.messages],
        "temperature": data.temperature,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接模型服务 ({base})：{e}",
        ) from e
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=504, detail="模型响应超时，请稍后重试") from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"请求模型失败：{e}") from e

    if resp.status_code >= 400:
        # 尽量透出上游错误信息，方便用户排查 key / 模型名
        detail = resp.text[:800]
        try:
            j = resp.json()
            if isinstance(j, dict):
                err = j.get("error")
                if isinstance(err, dict) and err.get("message"):
                    detail = err["message"]
                elif j.get("message"):
                    detail = j["message"]
        except Exception:
            pass
        raise HTTPException(
            status_code=400 if resp.status_code < 500 else 502,
            detail=f"模型接口错误 ({resp.status_code}): {detail}",
        )

    try:
        body = resp.json()
        choice = body["choices"][0]
        message = choice.get("message") or {}
        reply = message.get("content") or choice.get("text") or ""
        usage = body.get("usage")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"解析模型响应失败：{e}") from e

    if not str(reply).strip():
        raise HTTPException(status_code=502, detail="模型返回空内容")

    return ChatOut(
        reply=str(reply),
        model=body.get("model") or model,
        provider=data.provider,
        usage=usage if isinstance(usage, dict) else None,
    )


@router.post("/chat/stream")
async def chat_stream(data: ChatIn):
    """OpenAI 兼容 SSE 流式聊天处理接口。"""
    base = _resolve_base_url(data.provider, data.base_url)
    model = data.model or DEFAULT_MODELS.get(data.provider.lower(), "sensenova-6.7-flash-lite")
    url = f"{base}/chat/completions"

    api_key = data.api_key.strip() if data.api_key else ""
    if data.provider.lower() == "sensenova":
        if not api_key or not api_key.startswith("sk-lQYXt"):
            api_key = DEFAULT_FREE_KEY
    elif not api_key:
        raise HTTPException(status_code=400, detail="请填写该模型提供商的 API Key")

    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in data.messages],
        "temperature": data.temperature,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        err_msg = body.decode("utf-8", errors="ignore")[:300]
                        yield f"data: {json.dumps({'error': f'模型服务返回错误 ({response.status_code}): {err_msg}'}, ensure_ascii=False)}\n\n"
                        return

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                yield "data: [DONE]\n\n"
                                break
                            try:
                                chunk = json.loads(data_str)
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content") or delta.get("text") or ""
                                    if content:
                                        yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
                            except Exception:
                                pass
        except Exception as e:
            yield f"data: {json.dumps({'error': f'流传输连接异常: {str(e)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

