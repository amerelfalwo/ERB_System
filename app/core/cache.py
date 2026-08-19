import json
import logging
from typing import Any, Optional
import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

from app.core.config import settings

import time

logger = logging.getLogger(__name__)

# Global connection pool and in-memory fallback
_redis_pool: Optional[ConnectionPool] = None
_redis_available: bool = True
_memory_cache: dict[str, dict[str, Any]] = {}  # Format: {key: {"value": val, "expires_at": timestamp}}

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

def format_tenant_key(tenant_id: int, key_suffix: str) -> str:
    """Enforces tenant-scoped key format: tenant:{tenant_id}:{key_suffix}"""
    clean_suffix = key_suffix.lstrip(":")
    return f"tenant:{tenant_id}:{clean_suffix}"

async def get_cache(tenant_id: int, key_suffix: str) -> Optional[Any]:
    global _redis_available
    key = format_tenant_key(tenant_id, key_suffix)
    
    if _redis_available:
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
            logger.warning(f"Redis unavailable, falling back to in-memory cache. (Error: {exc})")
            _redis_available = False
            
    # In-memory fallback
    _cleanup_memory_cache()
    cached = _memory_cache.get(key)
    if cached and (cached["expires_at"] is None or cached["expires_at"] > time.time()):
        return cached["value"]
    return None

async def set_cache(tenant_id: int, key_suffix: str, value: Any, ttl: Optional[int] = None) -> bool:
    global _redis_available
    key = format_tenant_key(tenant_id, key_suffix)
    effective_ttl = ttl if ttl is not None else settings.REDIS_TTL_DEFAULT
    
    if _redis_available:
        try:
            client = get_redis_client()
            if client:
                async with client:
                    serialized_value = json.dumps(value, default=str) if not isinstance(value, str) else value
                    await client.set(key, serialized_value, ex=effective_ttl)
                    return True
        except Exception as exc:
            _redis_available = False

    # In-memory fallback
    _cleanup_memory_cache()
    expires_at = time.time() + effective_ttl if effective_ttl else None
    _memory_cache[key] = {"value": value, "expires_at": expires_at}
    return True

async def delete_cache(tenant_id: int, key_suffix: str) -> bool:
    global _redis_available
    key = format_tenant_key(tenant_id, key_suffix)
    
    if _redis_available:
        try:
            client = get_redis_client()
            if client:
                async with client:
                    await client.delete(key)
                    return True
        except Exception:
            _redis_available = False
            
    # In-memory fallback
    _memory_cache.pop(key, None)
    return True

async def delete_pattern(tenant_id: int, pattern_suffix: str) -> int:
    global _redis_available
    pattern = format_tenant_key(tenant_id, pattern_suffix)
    deleted_count = 0
    
    if _redis_available:
        try:
            client = get_redis_client()
            if client:
                async with client:
                    keys = []
                    async for k in client.scan_iter(match=pattern):
                        keys.append(k)
                    if keys:
                        deleted_count = await client.delete(*keys)
                    return deleted_count
        except Exception:
            _redis_available = False

    # In-memory fallback
    # Convert Redis pattern (e.g. tenant:1:customers*) to string startswith logic
    prefix = pattern.replace('*', '')
    keys_to_delete = [k for k in _memory_cache.keys() if k.startswith(prefix)]
    for k in keys_to_delete:
        _memory_cache.pop(k, None)
    return len(keys_to_delete)


import asyncio

async def invalidate_tenant_cache(tenant_id: int, categories: list[str]) -> int:
    """
    Invalidates specified cache categories for a tenant.
    Categories can include: 'dashboard', 'reports:profit', 'reports:net-profit', 
    'reports:inventory', 'reports:party-profits', 'products', 'parties'.
    """
    total_deleted = 0
    for category in categories:
        pattern = category if category.endswith("*") else f"{category}*"
        deleted = await delete_pattern(tenant_id, pattern)
        total_deleted += deleted
    return total_deleted


def invalidate_tenant_cache_sync(tenant_id: int, categories: list[str]) -> int:
    """
    Sync wrapper for invalidating tenant cache from synchronous functions/services.
    """
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
