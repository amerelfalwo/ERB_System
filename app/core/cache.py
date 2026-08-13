import json
import logging
from typing import Any, Optional
import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global connection pool
_redis_pool: Optional[ConnectionPool] = None

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
    """
    Retrieve cached value for a tenant key. Fail gracefully if Redis is unavailable.
    """
    key = format_tenant_key(tenant_id, key_suffix)
    try:
        client = get_redis_client()
        if client is None:
            return None
        async with client:
            val = await client.get(key)
            if val is not None:
                try:
                    return json.loads(val)
                except Exception:
                    return val
            return None
    except Exception as exc:
        logger.warning("Redis get_cache failed gracefully for key %s: %s", key, exc)
        return None

async def set_cache(tenant_id: int, key_suffix: str, value: Any, ttl: Optional[int] = None) -> bool:
    """
    Set cached value for a tenant key with TTL. Fail gracefully if Redis is unavailable.
    """
    key = format_tenant_key(tenant_id, key_suffix)
    effective_ttl = ttl if ttl is not None else settings.REDIS_TTL_DEFAULT
    try:
        client = get_redis_client()
        if client is None:
            return False
        async with client:
            serialized_value = json.dumps(value, default=str) if not isinstance(value, str) else value
            await client.set(key, serialized_value, ex=effective_ttl)
            return True
    except Exception as exc:
        logger.warning("Redis set_cache failed gracefully for key %s: %s", key, exc)
        return False

async def delete_cache(tenant_id: int, key_suffix: str) -> bool:
    """
    Delete a specific tenant cached key. Fail gracefully if Redis is unavailable.
    """
    key = format_tenant_key(tenant_id, key_suffix)
    try:
        client = get_redis_client()
        if client is None:
            return False
        async with client:
            await client.delete(key)
            return True
    except Exception as exc:
        logger.warning("Redis delete_cache failed gracefully for key %s: %s", key, exc)
        return False

async def delete_pattern(tenant_id: int, pattern_suffix: str) -> int:
    """
    Delete all keys matching pattern for a specific tenant. Fail gracefully if Redis is unavailable.
    """
    pattern = format_tenant_key(tenant_id, pattern_suffix)
    deleted_count = 0
    try:
        client = get_redis_client()
        if client is None:
            return 0
        async with client:
            keys = []
            async for k in client.scan_iter(match=pattern):
                keys.append(k)
            if keys:
                deleted_count = await client.delete(*keys)
            return deleted_count
    except Exception as exc:
        logger.warning("Redis delete_pattern failed gracefully for pattern %s: %s", pattern, exc)
        return 0


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
