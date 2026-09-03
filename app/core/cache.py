import json
import logging
import time
import asyncio
from decimal import Decimal
from datetime import datetime, date
from typing import Any, Optional, Callable
from functools import wraps
import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global connection pool & resilience state
_redis_pool: Optional[ConnectionPool] = None
_redis_available: bool = True
_last_redis_retry: float = 0.0
REDIS_RETRY_INTERVAL: float = 30.0  # Probe Redis recovery every 30 seconds

_memory_cache: dict[str, dict[str, Any]] = {}  # Format: {key: {"value": val, "expires_at": timestamp}}

# Custom Encoder for Decimal, datetime, and date objects
class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj) if obj.as_tuple().exponent != 0 else int(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()
        return super().default(obj)

def _cleanup_memory_cache():
    now = time.time()
    expired_keys = [k for k, v in _memory_cache.items() if v["expires_at"] and v["expires_at"] < now]
    for k in expired_keys:
        _memory_cache.pop(k, None)

def get_redis_pool() -> Optional[ConnectionPool]:
    global _redis_pool
    if _redis_pool is None:
        try:
            _redis_pool = ConnectionPool.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
        except Exception as e:
            logger.warning("Failed to initialize Redis ConnectionPool: %s", e)
            _redis_pool = None
    return _redis_pool

def get_redis_client() -> Optional[redis.Redis]:
    pool = get_redis_pool()
    if pool is None:
        return None
    return redis.Redis(connection_pool=pool)

async def check_redis_health() -> bool:
    """Checks if Redis is available or attempts auto-recovery after failure timeout."""
    global _redis_available, _last_redis_retry
    if _redis_available:
        return True
    
    now = time.time()
    if now - _last_redis_retry > REDIS_RETRY_INTERVAL:
        _last_redis_retry = now
        try:
            client = get_redis_client()
            if client:
                async with client:
                    if await client.ping():
                        _redis_available = True
                        logger.info("Redis connection recovered successfully!")
                        return True
        except Exception:
            pass
    return False

def format_tenant_key(tenant_id: int, key_suffix: str) -> str:
    """Enforces tenant-scoped key format: tenant:{tenant_id}:{key_suffix}"""
    clean_suffix = key_suffix.lstrip(":")
    return f"tenant:{tenant_id}:{clean_suffix}"

async def get_cache(tenant_id: int, key_suffix: str) -> Optional[Any]:
    global _redis_available, _last_redis_retry
    key = format_tenant_key(tenant_id, key_suffix)
    
    if await check_redis_health():
        try:
            client = get_redis_client()
            if client:
                async with client:
                    val = await client.get(key)
                    if val is not None:
                        try:
                            return json.loads(val)
                        except Exception:
                            return val
                    return None
        except Exception as exc:
            logger.warning(f"Redis error during get_cache, falling back to in-memory cache. (Error: {exc})")
            _redis_available = False
            _last_redis_retry = time.time()
            
    # In-memory fallback
    _cleanup_memory_cache()
    cached = _memory_cache.get(key)
    if cached and (cached["expires_at"] is None or cached["expires_at"] > time.time()):
        return cached["value"]
    return None

async def set_cache(tenant_id: int, key_suffix: str, value: Any, ttl: Optional[int] = None) -> bool:
    global _redis_available, _last_redis_retry
    key = format_tenant_key(tenant_id, key_suffix)
    effective_ttl = ttl if ttl is not None else settings.REDIS_TTL_DEFAULT
    
    if await check_redis_health():
        try:
            client = get_redis_client()
            if client:
                async with client:
                    serialized_value = json.dumps(value, cls=EnhancedJSONEncoder) if not isinstance(value, str) else value
                    await client.set(key, serialized_value, ex=effective_ttl)
                    return True
        except Exception as exc:
            logger.warning(f"Redis error during set_cache, falling back to in-memory cache. (Error: {exc})")
            _redis_available = False
            _last_redis_retry = time.time()

    # In-memory fallback
    _cleanup_memory_cache()
    expires_at = time.time() + effective_ttl if effective_ttl else None
    _memory_cache[key] = {"value": value, "expires_at": expires_at}
    return True

async def delete_cache(tenant_id: int, key_suffix: str) -> bool:
    global _redis_available, _last_redis_retry
    key = format_tenant_key(tenant_id, key_suffix)
    
    if await check_redis_health():
        try:
            client = get_redis_client()
            if client:
                async with client:
                    await client.delete(key)
                    return True
        except Exception as exc:
            logger.warning(f"Redis error during delete_cache: {exc}")
            _redis_available = False
            _last_redis_retry = time.time()
            
    # In-memory fallback
    _memory_cache.pop(key, None)
    return True

# Lua Script for Atomic Pattern Deletion in Redis
LUA_DELETE_PATTERN_SCRIPT = """
local keys = redis.call('KEYS', ARGV[1])
if #keys > 0 then
    return redis.call('DEL', unpack(keys))
end
return 0
"""

async def delete_pattern(tenant_id: int, pattern_suffix: str) -> int:
    global _redis_available, _last_redis_retry
    pattern = format_tenant_key(tenant_id, pattern_suffix)
    
    if await check_redis_health():
        try:
            client = get_redis_client()
            if client:
                async with client:
                    try:
                        deleted_count = await client.eval(LUA_DELETE_PATTERN_SCRIPT, 0, pattern)
                        return int(deleted_count)
                    except Exception:
                        keys = []
                        async for k in client.scan_iter(match=pattern):
                            keys.append(k)
                        if keys:
                            return await client.delete(*keys)
                        return 0
        except Exception as exc:
            logger.warning(f"Redis error during delete_pattern: {exc}")
            _redis_available = False
            _last_redis_retry = time.time()

    # In-memory fallback
    prefix = pattern.replace('*', '')
    keys_to_delete = [k for k in _memory_cache.keys() if k.startswith(prefix)]
    for k in keys_to_delete:
        _memory_cache.pop(k, None)
    return len(keys_to_delete)

async def invalidate_tenant_cache(tenant_id: int, categories: list[str]) -> int:
    total_deleted = 0
    for category in categories:
        pattern = category if category.endswith("*") else f"{category}*"
        deleted = await delete_pattern(tenant_id, pattern)
        total_deleted += deleted
    return total_deleted

def invalidate_tenant_cache_sync(tenant_id: int, categories: list[str]) -> int:
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(invalidate_tenant_cache(tenant_id, categories))
            return 0
        else:
            return asyncio.run(invalidate_tenant_cache(tenant_id, categories))
    except Exception as exc:
        logger.warning("Cache invalidation failed gracefully: %s", exc)
        return 0

def cache_response(ttl: Optional[int] = None, category: str = "endpoint"):
    """
    Decorator for FastAPI endpoint handlers to automatically cache response payloads.
    Requires `current_user` or `tenant_id` in function parameters/kwargs.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            tenant_id = None
            current_user = kwargs.get("current_user")
            if current_user and hasattr(current_user, "tenant_id"):
                tenant_id = current_user.tenant_id
            elif "tenant_id" in kwargs:
                tenant_id = kwargs["tenant_id"]

            if tenant_id is None:
                return await func(*args, **kwargs)

            param_str = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()) if k not in ("db", "current_user"))
            key_suffix = f"{category}:{func.__name__}:{param_str}"

            cached_data = await get_cache(tenant_id, key_suffix)
            if cached_data is not None:
                return cached_data

            response = await func(*args, **kwargs)
            if response is not None:
                await set_cache(tenant_id, key_suffix, response, ttl=ttl)
            return response
        return wrapper
    return decorator
