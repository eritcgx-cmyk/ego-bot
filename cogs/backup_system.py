"""
Comprehensive Server Backup System for Ego Bot.
Captures complete snapshots of server roles, members, member role assignments,
categories, channels, permission overwrites, emojis, and bot configuration states.
Saves local snapshots and provides downloadable JSON archives.
"""
import os
import json
import io
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands
from utils.permissions import is_guild_owner, is_admin_or_has_role
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed, card_embed,
    COLOR_VIOLET, COLOR_EMERALD, COLOR_CRIMSON, COLOR_CYAN
)
from config import logger

BACKUPS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "backups")

def ensure_backup_dir():
    os.makedirs(BACKUPS_DIR, exist_ok=True)

class BackupSystemCog(commands.Cog, name="Backup"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        ensure_backup_dir()

    backup_group = app_commands.Group(name="backup", description="Server backup snapshots (roles, members, channels, permissions)")

    @backup_group.command(name="create", description="Create a complete backup snapshot of server roles, members, channels, and configs")
    @app_commands.describe(note="Optional label or note for this backup")
    @is_guild_owner()
    async def backup_create(self, interaction: discord.Interaction, note: Optional[str] = None):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("❌ This command must be run in a server.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        # 1. Chunk guild to ensure 100% of members and roles are in memory
        try:
            if not guild.chunked:
                await guild.chunk()
        except Exception as e:
            logger.debug(f"Guild chunk note: {e}")

        now_utc = datetime.now(timezone.utc)
        timestamp_str = now_utc.strftime("%Y%m%d_%H%M%S")
        backup_id = f"backup_{guild.id}_{timestamp_str}"

        # 2. Extract Server Metadata
        server_meta = {
            "id": guild.id,
            "name": guild.name,
            "description": guild.description,
            "owner_id": guild.owner_id,
            "created_at": guild.created_at.isoformat() if guild.created_at else None,
            "icon_url": guild.icon.url if guild.icon else None,
            "banner_url": guild.banner.url if guild.banner else None,
            "splash_url": guild.splash.url if guild.splash else None,
            "member_count": guild.member_count,
            "verification_level": str(guild.verification_level),
            "default_notifications": str(guild.default_notifications),
            "explicit_content_filter": str(guild.explicit_content_filter),
            "afk_timeout": guild.afk_timeout,
            "afk_channel_id": guild.afk_channel.id if guild.afk_channel else None,
            "system_channel_id": guild.system_channel.id if guild.system_channel else None,
            "rules_channel_id": guild.rules_channel.id if guild.rules_channel else None,
            "public_updates_channel_id": guild.public_updates_channel.id if guild.public_updates_channel else None,
            "premium_tier": guild.premium_tier,
            "premium_subscription_count": guild.premium_subscription_count,
            "backup_timestamp": now_utc.isoformat(),
            "backup_note": note or "Manual Server Backup"
        }

        # 3. Extract All Roles
        roles_data = []
        for r in sorted(guild.roles, key=lambda x: x.position, reverse=True):
            if r.name == "@everyone":
                continue
            roles_data.append({
                "id": r.id,
                "name": r.name,
                "color_hex": f"#{r.color.value:06x}",
                "color_value": r.color.value,
                "position": r.position,
                "hoist": r.hoist,
                "mentionable": r.mentionable,
                "managed": r.managed,
                "permissions_value": r.permissions.value,
                "member_count": len(r.members)
            })

        # 4. Extract All Categories & Channels with Permissions
        categories_data = []
        for cat in guild.categories:
            overwrites = {}
            for target, ow in cat.overwrites.items():
                target_type = "role" if isinstance(target, discord.Role) else "member"
                target_name = target.name if isinstance(target, discord.Role) else str(target)
                overwrites[str(target.id)] = {
                    "type": target_type,
                    "name": target_name,
                    "allow": ow.pair()[0].value,
                    "deny": ow.pair()[1].value
                }
            categories_data.append({
                "id": cat.id,
                "name": cat.name,
                "position": cat.position,
                "overwrites": overwrites
            })

        channels_data = []
        for ch in guild.channels:
            if isinstance(ch, discord.CategoryChannel):
                continue

            ch_type = "text" if isinstance(ch, discord.TextChannel) else "voice" if isinstance(ch, discord.VoiceChannel) else "stage" if isinstance(ch, discord.StageChannel) else "forum" if isinstance(ch, discord.ForumChannel) else str(ch.type)
            
            overwrites = {}
            for target, ow in ch.overwrites.items():
                target_type = "role" if isinstance(target, discord.Role) else "member"
                target_name = target.name if isinstance(target, discord.Role) else str(target)
                overwrites[str(target.id)] = {
                    "type": target_type,
                    "name": target_name,
                    "allow": ow.pair()[0].value,
                    "deny": ow.pair()[1].value
                }

            ch_info = {
                "id": ch.id,
                "name": ch.name,
                "type": ch_type,
                "position": ch.position,
                "category_id": ch.category_id,
                "overwrites": overwrites
            }

            if isinstance(ch, discord.TextChannel):
                ch_info["topic"] = ch.topic
                ch_info["nsfw"] = ch.nsfw
                ch_info["slowmode_delay"] = ch.slowmode_delay
            elif isinstance(ch, discord.VoiceChannel):
                ch_info["bitrate"] = ch.bitrate
                ch_info["user_limit"] = ch.user_limit

            channels_data.append(ch_info)

        # 5. Extract All Members and Assigned Roles
        members_data = []
        for m in guild.members:
            assigned_role_ids = [r.id for r in m.roles if r.name != "@everyone"]
            assigned_role_names = [r.name for r in m.roles if r.name != "@everyone"]
            members_data.append({
                "id": m.id,
                "name": m.name,
                "display_name": m.display_name,
                "nick": m.nick,
                "bot": m.bot,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "avatar_url": m.display_avatar.url if m.display_avatar else None,
                "role_ids": assigned_role_ids,
                "role_names": assigned_role_names
            })

        # 6. Extract Emojis and Stickers
        emojis_data = []
        for emo in guild.emojis:
            emojis_data.append({
                "id": emo.id,
                "name": emo.name,
                "animated": emo.animated,
                "url": emo.url
            })

        # 7. Compile Complete Backup Payload
        backup_payload = {
            "version": "2.0",
            "backup_id": backup_id,
            "guild": server_meta,
            "roles": roles_data,
            "categories": categories_data,
            "channels": channels_data,
            "members": members_data,
            "emojis": emojis_data
        }

        # 8. Save JSON to Local Storage
        file_path = os.path.join(BACKUPS_DIR, f"{backup_id}.json")
        json_bytes = json.dumps(backup_payload, indent=2).encode("utf-8")
        with open(file_path, "wb") as f:
            f.write(json_bytes)

        file_size_kb = len(json_bytes) / 1024

        # 9. Build Summary Embed
        embed = ego_embed(
            title="Server Backup Created",
            description=(
                f"> **Server:** `{guild.name}` (`{guild.id}`)\n"
                f"> **Backup ID:** `{backup_id}`\n"
                f"> **Label / Note:** *{note or 'Manual Server Backup'}*\n"
                f"> **Timestamp:** <t:{int(now_utc.timestamp())}:F>\n\n"
                f"**✦ Snapshot Statistics:**\n"
                f"• **Members & Role Assignments:** `{len(members_data)}` members\n"
                f"• **Custom Roles:** `{len(roles_data)}` roles\n"
                f"• **Categories & Channels:** `{len(categories_data)}` categories, `{len(channels_data)}` channels\n"
                f"• **Custom Emojis:** `{len(emojis_data)}` emojis\n"
                f"• **Archive Size:** `{file_size_kb:.1f} KB`\n\n"
                f"The complete JSON archive is attached below for secure offline storage."
            ),
            color=COLOR_EMERALD
        )

        discord_file = discord.File(fp=io.BytesIO(json_bytes), filename=f"{backup_id}.json")
        await interaction.followup.send(embed=embed, file=discord_file)

    @backup_group.command(name="list", description="List all server backups saved locally")
    @is_admin_or_has_role()
    async def backup_list(self, interaction: discord.Interaction):
        guild = interaction.guild
        ensure_backup_dir()

        files = [f for f in os.listdir(BACKUPS_DIR) if f.startswith(f"backup_{guild.id}_") and f.endswith(".json")]
        if not files:
            return await interaction.response.send_message(
                embed=info_embed("No Backups Found", "No local backups exist for this server yet.\nRun `/backup create` to take your first snapshot!"),
                ephemeral=True
            )

        files.sort(reverse=True)
        embed = ego_embed(
            title=f"Server Backups • {guild.name}",
            description=f"> Total Available Backups: **`{len(files)}`**\n",
            color=COLOR_VIOLET
        )

        for fname in files[:10]:
            fpath = os.path.join(BACKUPS_DIR, fname)
            size_kb = os.path.getsize(fpath) / 1024
            mod_time = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)

            note = "Standard Backup"
            m_count = 0
            r_count = 0
            try:
                with open(fpath, "r", encoding="utf-8") as bf:
                    data = json.load(bf)
                    note = data.get("guild", {}).get("backup_note", "Standard Backup")
                    m_count = len(data.get("members", []))
                    r_count = len(data.get("roles", []))
            except Exception:
                pass

            embed.add_field(
                name=f"💾 `{fname.replace('.json', '')}`",
                value=(
                    f"• **Note:** *{note}*\n"
                    f"• **Members:** `{m_count}` | **Roles:** `{r_count}`\n"
                    f"• **Size:** `{size_kb:.1f} KB` | <t:{int(mod_time.timestamp())}:R>"
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @backup_group.command(name="download", description="Download a specific backup file by ID")
    @app_commands.describe(backup_id="The ID of the backup to download (e.g. backup_12345_20260819_155300)")
    @is_guild_owner()
    async def backup_download(self, interaction: discord.Interaction, backup_id: str):
        ensure_backup_dir()
        clean_id = backup_id.strip().replace(".json", "")
        fpath = os.path.join(BACKUPS_DIR, f"{clean_id}.json")

        if not os.path.exists(fpath):
            return await interaction.response.send_message(
                embed=error_embed("Backup Not Found", f"No backup file found matching ID `{clean_id}`."),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        discord_file = discord.File(fpath, filename=f"{clean_id}.json")
        await interaction.followup.send(
            embed=success_embed("Backup Ready", f"Attached backup file for `{clean_id}`:"),
            file=discord_file
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(BackupSystemCog(bot))
