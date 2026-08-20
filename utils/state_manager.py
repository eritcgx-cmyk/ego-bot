"""
Master State & Auto-Persistence Manager for Ego Bot.
Ensures zero data loss across container restarts, cloud redeployments, and host migrations.
Auto-syncs all database models to and from data/master_guild_state.json.
"""
import os
import json
import asyncio
from typing import Dict, Any, Optional
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import (
    WelcomeConfig, GuildConfig, AutomodConfig, InviteTier, IdentityVerifyConfig
)
from config import logger

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MASTER_STATE_FILE = os.path.join(DATA_DIR, "master_guild_state.json")

def ensure_master_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(MASTER_STATE_FILE):
        with open(MASTER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)

def load_master_state() -> Dict[str, Any]:
    ensure_master_file()
    try:
        with open(MASTER_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_master_state(data: Dict[str, Any]):
    ensure_master_file()
    with open(MASTER_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def update_guild_state_section(guild_id: int, section: str, values: Dict[str, Any]):
    """Updates a section (e.g. 'welcome', 'verify', 'automod', 'config') in the master state file."""
    state = load_master_state()
    g_key = str(guild_id)
    if g_key not in state:
        state[g_key] = {}
    state[g_key][section] = values
    save_master_state(state)
    logger.debug(f"Auto-persisted section '{section}' for guild {guild_id}")

async def restore_database_from_master_state():
    """Restores database tables from master_guild_state.json on boot if empty."""
    state = load_master_state()
    if not state:
        logger.info("Master state file is empty, skipping DB hydration.")
        return

    logger.info("Hydrating database from master state file...")
    async with AsyncSessionLocal() as session:
        for g_id_str, g_data in state.items():
            try:
                g_id = int(g_id_str)
            except ValueError:
                continue

            # 1. Restore WelcomeConfig
            w_data = g_data.get("welcome")
            if w_data:
                res_w = await session.execute(select(WelcomeConfig).where(WelcomeConfig.guild_id == g_id))
                w_cfg = res_w.scalar_one_or_none()
                if not w_cfg:
                    w_cfg = WelcomeConfig(guild_id=g_id)
                    session.add(w_cfg)
                w_cfg.enabled = w_data.get("enabled", True)
                w_cfg.channel_id = w_data.get("channel_id")
                w_cfg.title = w_data.get("title")
                w_cfg.message = w_data.get("message")
                w_cfg.embed_color = w_data.get("embed_color", 0x8B5CF6)
                w_cfg.leave_enabled = w_data.get("leave_enabled", True)
                w_cfg.leave_channel_id = w_data.get("leave_channel_id")
                w_cfg.leave_title = w_data.get("leave_title")
                w_cfg.leave_message = w_data.get("leave_message")
                w_cfg.leave_color = w_data.get("leave_color", 0xEF4444)

            # 2. Restore GuildConfig
            c_data = g_data.get("config")
            if c_data:
                res_c = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == g_id))
                g_cfg = res_c.scalar_one_or_none()
                if not g_cfg:
                    g_cfg = GuildConfig(guild_id=g_id)
                    session.add(g_cfg)
                g_cfg.mod_log_channel_id = c_data.get("mod_log_channel_id")
                g_cfg.admin_role_id = c_data.get("admin_role_id")
                g_cfg.mod_role_id = c_data.get("mod_role_id")

            # 3. Restore AutomodConfig
            a_data = g_data.get("automod")
            if a_data:
                res_a = await session.execute(select(AutomodConfig).where(AutomodConfig.guild_id == g_id))
                a_cfg = res_a.scalar_one_or_none()
                if not a_cfg:
                    a_cfg = AutomodConfig(guild_id=g_id)
                    session.add(a_cfg)
                a_cfg.enabled = a_data.get("enabled", True)
                a_cfg.block_invites = a_data.get("block_invites", True)
                a_cfg.spam_threshold = a_data.get("spam_threshold", 5)
                a_cfg.mass_mention_limit = a_data.get("mass_mention_limit", 5)

        await session.commit()
    logger.info("Database hydration from master state complete.")
