from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatIn(BaseModel):
    """OpenAI 兼容聊天请求。API Key 仅本次请求使用，不落库。"""

    provider: str = Field(default="deepseek", max_length=32)
    api_key: str = Field(min_length=1, max_length=512)
    base_url: Optional[str] = Field(default=None, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    messages: list[ChatMessage] = Field(min_length=1, max_length=80)
    temperature: float = Field(default=0.7, ge=0, le=2)

    @field_validator("api_key", "model", "provider", mode="before")
    @classmethod
    def strip_required(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, v):
        if v is None:
            return None
        s = str(v).strip().rstrip("/")
        return s or None


class ChatOut(BaseModel):
    reply: str
    model: str
    provider: str
    usage: Optional[dict] = None
