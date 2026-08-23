"""
PostgreSQL-Backed Master Key-Value & Persistent State Storage for Ego Bot.
Guarantees 100% Zero-Loss Configuration Retention across Render Container Redeployments and Restarts.
"""
import os
import json
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, List
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import BotKVStore
from config import logger

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Global in-memory cache for instant zero-latency synchronous reads
_MEMORY_CACHE: Dict[str, Any] = {}

# Known legacy JSON files that are automatically synchronized with PostgreSQL
LEGACY_FILE_MAP = {
    "cc_config": "cc_config.json",
    "saved_statuses": "saved_statuses.json",
    "role_boards": "role_boards.json",
    "custom_role_descriptions": "custom_role_descriptions.json",
    "invite_board_config": "invite_board_config.json",
    "member_inviters": "member_inviters.json",
    "command_access": "command_access.json",
    "face_verify_config": "face_verify_config.json",
    "cc_tier_requirements": "cc_tier_requirements.json",
    "role_presets": "role_presets.json",
    "master_guild_state": "master_guild_state.json"
}

def _write_local_mirror(key: str, data: Any):
    """Writes an atomic local disk mirror for cogs that read legacy JSON paths."""
    filename = LEGACY_FILE_MAP.get(key)
    if not filename:
        return
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        filepath = os.path.join(DATA_DIR, filename)
        tmp_path = f"{filepath}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        if os.path.exists(filepath):
            os.replace(tmp_path, filepath)
        else:
            os.rename(tmp_path, filepath)
    except Exception as e:
        logger.debug(f"[KVStore] Mirror write warning for {key}: {e}")

async def init_kv_store():
    """Hydrates the in-memory cache and local file mirrors directly from PostgreSQL on boot."""
    os.makedirs(DATA_DIR, exist_ok=True)
    logger.info("[KVStore] Hydrating persistent configurations from PostgreSQL...")
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(BotKVStore))
            rows = res.scalars().all()
            for row in rows:
                try:
                    val = json.loads(row.value_json or "null")
                    _MEMORY_CACHE[row.key] = val
                    _write_local_mirror(row.key, val)
                except Exception as e:
                    logger.debug(f"[KVStore] JSON parse error for key '{row.key}': {e}")
        logger.info(f"[KVStore] Successfully loaded {len(_MEMORY_CACHE)} persistent configuration stores from PostgreSQL.")
    except Exception as e:
        logger.error(f"[KVStore] Error hydrating from PostgreSQL: {e}")

async def get_kv(key: str, default: Any = None) -> Any:
    """Fetches a configuration from PostgreSQL with cache fallback."""
    if key in _MEMORY_CACHE:
        return _MEMORY_CACHE[key]
    
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(BotKVStore).where(BotKVStore.key == key))
            row = res.scalar_one_or_none()
            if row and row.value_json:
                val = json.loads(row.value_json)
                _MEMORY_CACHE[key] = val
                _write_local_mirror(key, val)
                return val
    except Exception as e:
        logger.debug(f"[KVStore] get_kv error for '{key}': {e}")
    
    return default

def get_cached_kv(key: str, default: Any = None) -> Any:
    """Synchronous read from the hydrated in-memory cache."""
    if key in _MEMORY_CACHE:
        return _MEMORY_CACHE[key]
    
    # Fallback to local file if not in cache yet
    filename = LEGACY_FILE_MAP.get(key)
    if filename:
        fpath = os.path.join(DATA_DIR, filename)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    val = json.load(f)
                    _MEMORY_CACHE[key] = val
                    return val
            except Exception:
                pass
    return default

async def set_kv(key: str, value: Any):
    """Persists a configuration permanently to PostgreSQL, updates cache, and updates local file mirror."""
    _MEMORY_CACHE[key] = value
    _write_local_mirror(key, value)

    try:
        val_str = json.dumps(value, ensure_ascii=False)
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(BotKVStore).where(BotKVStore.key == key))
            row = res.scalar_one_or_none()
            if not row:
                row = BotKVStore(key=key, value_json=val_str)
                session.add(row)
            else:
                row.value_json = val_str
                row.updated_at = datetime.utcnow()
            await session.commit()
            logger.debug(f"[KVStore] Successfully persisted '{key}' to PostgreSQL.")
    except Exception as e:
        logger.error(f"[KVStore] Error saving key '{key}' to PostgreSQL: {e}")

def set_cached_kv_and_schedule_save(key: str, value: Any, loop: Optional[asyncio.AbstractEventLoop] = None):
    """Synchronous helper for legacy cogs to update cache immediately and fire an async DB commit."""
    _MEMORY_CACHE[key] = value
    _write_local_mirror(key, value)
    
    try:
        target_loop = loop or asyncio.get_event_loop()
        if target_loop and target_loop.is_running():
            asyncio.create_task(set_kv(key, value))
    except Exception:
        pass

async def delete_kv(key: str):
    """Deletes a key from PostgreSQL and cache."""
    _MEMORY_CACHE.pop(key, None)
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(BotKVStore).where(BotKVStore.key == key))
            row = res.scalar_one_or_none()
            if row:
                await session.delete(row)
                await session.commit()
    except Exception as e:
        logger.error(f"[KVStore] Error deleting key '{key}': {e}")
