import time
from typing import Optional

from .dexscreener import TokenData

_user_pending_token: dict[int, TokenData] = {}
_token_cache: dict[str, tuple[TokenData, float]] = {}
CACHE_TTL_SEC = 45


def get_pending_token(user_id: int) -> Optional[TokenData]:
    return _user_pending_token.get(user_id)


def set_pending_token(user_id: int, data: TokenData) -> None:
    _user_pending_token[user_id] = data


def clear_pending_token(user_id: int) -> None:
    _user_pending_token.pop(user_id, None)


def get_cached_token(token_address: str) -> Optional[TokenData]:
    key = token_address.lower()
    if key not in _token_cache:
        return None
    data, ts = _token_cache[key]
    if time.time() - ts > CACHE_TTL_SEC:
        del _token_cache[key]
        return None
    return data


def set_cached_token(token_address: str, data: TokenData) -> None:
    _token_cache[token_address.lower()] = (data, time.time())
