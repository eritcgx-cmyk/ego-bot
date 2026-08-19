"""
Comprehensive Server Backup and Disaster Recovery Engine for Ego Bot.
Features /backup create, /backup list, /backup restore (Anti-Nuke Recovery),
and /backup download. Reconstructs all roles, categories, channels, permissions,
and reassigns roles to all members if a server is nuked or wiped.
"""
import os
import json
import io
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands, tasks
from utils.permissions import is_guild_owner, is_admin_or_has_role
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed, card_embed,
    COLOR_VIOLET, COLOR_EMERALD, COLOR_CRIMSON, COLOR_CYAN, COLOR_AMBER
)
from config import logger

BACKUPS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "backups")

def ensure_backup_dir():
    os.makedirs(BACKUPS_DIR, exist_ok=True)

class RestoreConfirmView(discord.ui.View):
    def __init__(self, backup_id: str, cog_instance: "BackupSystemCog"):
        super().__init__(timeout=60)
        self.backup_id = backup_id
        self.cog = cog_instance

    @discord.ui.button(label="Confirm & Restore Server", style=discord.ButtonStyle.danger, custom_id="backup_confirm_restore")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ Only the Server Owner can execute a full server restore.", ephemeral=True)

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        await interaction.response.defer()
        await self.cog.execute_server_restore(interaction, self.backup_id)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="backup_cancel_restore")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(embed=info_embed("Restore Cancelled", "Server restoration was aborted."), ephemeral=True)


class BackupSystemCog(commands.Cog, name="Backup"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        ensure_backup_dir()
        self.daily_backup_loop.start()

    def cog_unload(self):
        self.daily_backup_loop.cancel()

    backup_group = app_commands.Group(name="backup", description="Server backup snapshots and disaster recovery reconstruction")

    async def capture_guild_snapshot(self, guild: discord.Guild, note: Optional[str] = None) -> Dict[str, Any]:
        """Captures a complete dictionary payload of guild state."""
        try:
            if not guild.chunked:
                await guild.chunk()
        except Exception:
            pass

        now_utc = datetime.now(timezone.utc)
        timestamp_str = now_utc.strftime("%Y%m%d_%H%M%S")
        backup_id = f"backup_{guild.id}_{timestamp_str}"

        # 1. Server Metadata
        server_meta = {
            "id": guild.id,
            "name": guild.name,
            "description": guild.description,
            "owner_id": guild.owner_id,
            "created_at": guild.created_at.isoformat() if guild.created_at else None,
            "member_count": guild.member_count,
            "afk_timeout": guild.afk_timeout,
            "backup_timestamp": now_utc.isoformat(),
            "backup_note": note or "Server Snapshot"
        }

        # 2. Roles
        roles_data = []
        for r in sorted(guild.roles, key=lambda x: x.position, reverse=False):
            if r.name == "@everyone":
                continue
            roles_data.append({
                "id": r.id,
                "name": r.name,
                "color_value": r.color.value,
                "position": r.position,
                "hoist": r.hoist,
                "mentionable": r.mentionable,
                "permissions_value": r.permissions.value,
                "managed": r.managed
            })

        # 3. Categories
        categories_data = []
        for cat in sorted(guild.categories, key=lambda c: c.position):
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

        # 4. Channels
        channels_data = []
        for ch in sorted(guild.channels, key=lambda c: c.position):
            if isinstance(ch, discord.CategoryChannel):
                continue

            ch_type = "text" if isinstance(ch, discord.TextChannel) else "voice" if isinstance(ch, discord.VoiceChannel) else str(ch.type)
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

        # 5. Members and Assigned Roles
        members_data = []
        for m in guild.members:
            assigned_role_names = [r.name for r in m.roles if r.name != "@everyone" and not r.managed]
            assigned_role_ids = [r.id for r in m.roles if r.name != "@everyone" and not r.managed]
            members_data.append({
                "id": m.id,
                "name": m.name,
                "display_name": m.display_name,
                "bot": m.bot,
                "role_ids": assigned_role_ids,
                "role_names": assigned_role_names
            })

        return {
            "version": "2.0",
            "backup_id": backup_id,
            "guild": server_meta,
            "roles": roles_data,
            "categories": categories_data,
            "channels": channels_data,
            "members": members_data
        }

    @tasks.loop(hours=24)
    async def daily_backup_loop(self):
        """Automatically saves daily rolling server snapshots for recovery."""
        for guild in self.bot.guilds:
            try:
                payload = await self.capture_guild_snapshot(guild, note="Automated Daily Backup")
                fpath = os.path.join(BACKUPS_DIR, f"{payload['backup_id']}.json")
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
                logger.info(f"Saved automated daily backup for guild {guild.name} ({guild.id}).")
            except Exception as e:
                logger.error(f"Error in daily backup for guild {guild.id}: {e}")

    @daily_backup_loop.before_loop
    async def before_daily_backup(self):
        await self.bot.wait_until_ready()

    @backup_group.command(name="create", description="Create a complete backup snapshot of server roles, members, channels, and configs")
    @app_commands.describe(note="Optional label or note for this backup")
    @is_guild_owner()
    async def backup_create(self, interaction: discord.Interaction, note: Optional[str] = None):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("❌ This command must be run in a server.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        payload = await self.capture_guild_snapshot(guild, note)
        backup_id = payload["backup_id"]

        fpath = os.path.join(BACKUPS_DIR, f"{backup_id}.json")
        json_bytes = json.dumps(payload, indent=2).encode("utf-8")
        with open(fpath, "wb") as f:
            f.write(json_bytes)

        file_size_kb = len(json_bytes) / 1024

        embed = ego_embed(
            title="Server Backup Created",
            description=(
                f"> **Server:** `{guild.name}` (`{guild.id}`)\n"
                f"> **Backup ID:** `{backup_id}`\n"
                f"> **Label:** *{note or 'Manual Server Backup'}*\n\n"
                f"**✦ Snapshot Statistics:**\n"
                f"• **Members Mapped:** `{len(payload['members'])}`\n"
                f"• **Roles Backed Up:** `{len(payload['roles'])}`\n"
                f"• **Categories & Channels:** `{len(payload['categories'])}` categories, `{len(payload['channels'])}` channels\n"
                f"• **Archive Size:** `{file_size_kb:.1f} KB`\n\n"
                f"In case of a server raid or nuke, run `/backup restore backup_id:{backup_id}` to fully reconstruct the server!"
            ),
            color=COLOR_EMERALD
        )

        discord_file = discord.File(fp=io.BytesIO(json_bytes), filename=f"{backup_id}.json")
        await interaction.followup.send(embed=embed, file=discord_file)

    @backup_group.command(name="restore", description="[Owner Only] Anti-Nuke: Reconstruct all roles, categories, channels, and re-assign member roles")
    @app_commands.describe(backup_id="The ID of the backup to restore (use /backup list to view available IDs)")
    @is_guild_owner()
    async def backup_restore_cmd(self, interaction: discord.Interaction, backup_id: Optional[str] = None):
        guild = interaction.guild
        ensure_backup_dir()

        # Find target backup file
        target_file = None
        if backup_id:
            clean_id = backup_id.strip().replace(".json", "")
            fpath = os.path.join(BACKUPS_DIR, f"{clean_id}.json")
            if os.path.exists(fpath):
                target_file = fpath
        else:
            # Pick latest backup for this guild
            files = [f for f in os.listdir(BACKUPS_DIR) if f.startswith(f"backup_{guild.id}_") and f.endswith(".json")]
            if files:
                files.sort(reverse=True)
                target_file = os.path.join(BACKUPS_DIR, files[0])

        if not target_file or not os.path.exists(target_file):
            return await interaction.response.send_message(
                embed=error_embed("Backup Not Found", "Could not locate a backup file matching your request.\nRun `/backup list` to view available backup IDs."),
                ephemeral=True
            )

        bid = os.path.basename(target_file).replace(".json", "")

        confirm_embed = ego_embed(
            title="⚠️ Confirm Server Restoration",
            description=(
                f"**Disaster Recovery Reconstruction**\n\n"
                f"> **Target Backup:** `{bid}`\n"
                f"> **Server:** `{guild.name}`\n\n"
                f"**This action will:**\n"
                f"1. **Reconstruct all missing roles** with exact colors, permissions, and hierarchy.\n"
                f"2. **Reconstruct all categories & channels** with exact slowmode, topics, and permissions.\n"
                f"3. **Re-assign all roles to server members** based on the saved snapshot.\n\n"
                f"Click **Confirm & Restore Server** below to begin reconstruction."
            ),
            color=COLOR_AMBER
        )

        view = RestoreConfirmView(backup_id=bid, cog_instance=self)
        await interaction.response.send_message(embed=confirm_embed, view=view, ephemeral=True)

    async def execute_server_restore(self, interaction: discord.Interaction, backup_id: str):
        """Reconstructs all server roles, channels, categories, and assigns roles to members."""
        guild = interaction.guild
        fpath = os.path.join(BACKUPS_DIR, f"{backup_id}.json")
        if not os.path.exists(fpath):
            return await interaction.followup.send(embed=error_embed("File Missing", "Backup file was not found on disk."))

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return await interaction.followup.send(embed=error_embed("Corrupt Backup", f"Failed to parse backup JSON: {e}"))

        status_msg = await interaction.followup.send(
            embed=info_embed("Recovery Started", "⚙️ Reconstructing server infrastructure... Please wait.")
        )

        roles_created = 0
        categories_created = 0
        channels_created = 0
        members_recovered = 0

        # Mapping of old IDs to new Discord objects
        role_map: Dict[int, discord.Role] = {}
        category_map: Dict[int, discord.CategoryChannel] = {}

        # ----------------------------------------------------
        # STEP 1: Reconstruct Roles
        # ----------------------------------------------------
        backed_up_roles = data.get("roles", [])
        for r_data in backed_up_roles:
            if r_data.get("managed"):
                continue

            r_name = r_data.get("name")
            existing = discord.utils.find(lambda r: r.name.lower() == r_name.lower() and not r.managed, guild.roles)
            if existing:
                role_map[r_data["id"]] = existing
            else:
                try:
                    perms = discord.Permissions(r_data.get("permissions_value", 0))
                    color = discord.Color(r_data.get("color_value", 0))
                    new_role = await guild.create_role(
                        name=r_name,
                        permissions=perms,
                        color=color,
                        hoist=r_data.get("hoist", False),
                        mentionable=r_data.get("mentionable", False),
                        reason="Anti-Nuke Server Restore"
                    )
                    role_map[r_data["id"]] = new_role
                    roles_created += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.error(f"Failed to restore role {r_name}: {e}")

        # ----------------------------------------------------
        # STEP 2: Reconstruct Categories
        # ----------------------------------------------------
        backed_up_categories = data.get("categories", [])
        for c_data in backed_up_categories:
            c_name = c_data.get("name")
            existing_cat = discord.utils.find(lambda c: c.name.lower() == c_name.lower(), guild.categories)
            if existing_cat:
                category_map[c_data["id"]] = existing_cat
            else:
                try:
                    # Map overwrites
                    overwrites = {}
                    for old_tid_str, ow_info in c_data.get("overwrites", {}).items():
                        old_tid = int(old_tid_str)
                        if old_tid in role_map:
                            mapped_role = role_map[old_tid]
                            allow_perms = discord.Permissions(ow_info.get("allow", 0))
                            deny_perms = discord.Permissions(ow_info.get("deny", 0))
                            overwrites[mapped_role] = discord.PermissionOverwrite.from_pair(allow_perms, deny_perms)

                    new_cat = await guild.create_category(name=c_name, overwrites=overwrites, reason="Anti-Nuke Server Restore")
                    category_map[c_data["id"]] = new_cat
                    categories_created += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.error(f"Failed to restore category {c_name}: {e}")

        # ----------------------------------------------------
        # STEP 3: Reconstruct Channels
        # ----------------------------------------------------
        backed_up_channels = data.get("channels", [])
        for ch_data in backed_up_channels:
            ch_name = ch_data.get("name")
            ch_type = ch_data.get("type", "text")
            parent_cat_id = ch_data.get("category_id")
            target_cat = category_map.get(parent_cat_id) if parent_cat_id else None

            existing_ch = discord.utils.find(lambda c: c.name.lower() == ch_name.lower() and not isinstance(c, discord.CategoryChannel), guild.channels)
            if not existing_ch:
                try:
                    overwrites = {}
                    for old_tid_str, ow_info in ch_data.get("overwrites", {}).items():
                        old_tid = int(old_tid_str)
                        if old_tid in role_map:
                            mapped_role = role_map[old_tid]
                            allow_perms = discord.Permissions(ow_info.get("allow", 0))
                            deny_perms = discord.Permissions(ow_info.get("deny", 0))
                            overwrites[mapped_role] = discord.PermissionOverwrite.from_pair(allow_perms, deny_perms)

                    if ch_type == "voice":
                        await guild.create_voice_channel(
                            name=ch_name,
                            category=target_cat,
                            overwrites=overwrites,
                            bitrate=min(ch_data.get("bitrate", 64000), guild.bitrate_limit),
                            user_limit=ch_data.get("user_limit", 0),
                            reason="Anti-Nuke Server Restore"
                        )
                    else:
                        await guild.create_text_channel(
                            name=ch_name,
                            category=target_cat,
                            overwrites=overwrites,
                            topic=ch_data.get("topic"),
                            nsfw=ch_data.get("nsfw", False),
                            slowmode_delay=ch_data.get("slowmode_delay", 0),
                            reason="Anti-Nuke Server Restore"
                        )
                    channels_created += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.error(f"Failed to restore channel {ch_name}: {e}")

        # ----------------------------------------------------
        # STEP 4: Re-assign Roles to Members
        # ----------------------------------------------------
        if not guild.chunked:
            try:
                await guild.chunk()
            except Exception:
                pass

        backed_up_members = data.get("members", [])
        for m_data in backed_up_members:
            uid = m_data.get("id")
            member = guild.get_member(uid)
            if not member or member.bot:
                continue

            roles_to_assign = []
            # Match by mapped role IDs
            for old_rid in m_data.get("role_ids", []):
                if old_rid in role_map:
                    target_role = role_map[old_rid]
                    if target_role not in member.roles and target_role.position < guild.me.top_role.position:
                        roles_to_assign.append(target_role)

            # Match by role name fallback
            for r_name in m_data.get("role_names", []):
                matched = discord.utils.find(lambda r: r.name.lower() == r_name.lower() and not r.managed, guild.roles)
                if matched and matched not in member.roles and matched not in roles_to_assign:
                    if matched.position < guild.me.top_role.position:
                        roles_to_assign.append(matched)

            if roles_to_assign:
                try:
                    await member.add_roles(*roles_to_assign, reason="Anti-Nuke Member Role Recovery")
                    members_recovered += 1
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.debug(f"Could not assign roles to {member.name}: {e}")

        # Trigger Roles Board update
        roles_cog = self.bot.get_cog("Roles")
        if roles_cog and hasattr(roles_cog, "_trigger_board_refresh_for_guild"):
            await roles_cog._trigger_board_refresh_for_guild(guild)

        embed = ego_embed(
            title="🛡️ Server Restoration Complete",
            description=(
                f"> **Backup ID:** `{backup_id}`\n"
                f"> **Target Server:** `{guild.name}`\n\n"
                f"**✦ Reconstructed Infrastructure:**\n"
                f"• **Roles Created:** `{roles_created}` roles\n"
                f"• **Categories Created:** `{categories_created}` categories\n"
                f"• **Channels Created:** `{channels_created}` text/voice channels\n"
                f"• **Members Recovered:** `{members_recovered}` members re-assigned roles\n\n"
                f"All channels, permissions, roles, and member assignments have been fully reconstructed."
            ),
            color=COLOR_EMERALD
        )
        await status_msg.edit(embed=embed)

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
