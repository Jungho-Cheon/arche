"""Opentology 코어 호출 클라이언트 — REST (MVP). MCP 어댑터는 #7 의존."""

from .opentology import (
    OpentologyClient,
    OpentologyClientError,
    OpentologyUnavailableError,
    PrimitiveCall,
)

__all__ = [
    "OpentologyClient",
    "OpentologyClientError",
    "OpentologyUnavailableError",
    "PrimitiveCall",
]
