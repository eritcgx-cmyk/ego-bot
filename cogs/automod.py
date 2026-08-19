"""
Automod and Escalation System Cog for Ego Bot
"""
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func
from database.engine import AsyncSessionLocal
from database.models import AutomodConfig, AutomodInfraction
from utils.permissions import is_admin_or_has_role, is_mod_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, warning_embed, info_embed
from utils.logger import log_action
from config import ERROR_COLOR, WARNING_COLOR, logger

INVITE_REGEX = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li|com/invite)/[a-zA-Z0-9]+)", re.IGNORECASE)

class AutomodCog(commands.Cog, name="Automod"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # In-memory message timestamps for spam tracking: {guild_id: {user_id: [timestamps]}}
        self.spam_tracker: Dict[int, Dict[int, List[float]]] = defaultdict(lambda: defaultdict(list))

    async def _escalate_action(self, message: discord.Message, reason: str, cfg: AutomodConfig):
        """Record infraction and execute escalation (warn -> timeout -> kick -> ban)."""
        guild = message.guild
        member = message.author
        if not isinstance(member, discord.Member):
            return

        async with AsyncSessionLocal() as session:
            # Add infraction record
            infraction = AutomodInfraction(
                guild_id=guild.id,
                user_id=member.id,
                action_type="trigger",
                reason=reason,
                points=1
            )
            session.add(infraction)
            await session.commit()

            # Count total infractions
            res = await session.execute(
                select(func.count(AutomodInfraction.id)).where(
                    AutomodInfraction.guild_id == guild.id,
                    AutomodInfraction.user_id == member.id
                )
            )
            total_points = res.scalar() or 1

        action_taken = "Warn"
        try:
            if total_points >= cfg.ban_threshold:
                action_taken = "Ban"
                await member.ban(reason=f"[Automod Escalation] {reason} (Infraction #{total_points})")
            elif total_points >= cfg.kick_threshold:
                action_taken = "Kick"
                await member.kick(reason=f"[Automod Escalation] {reason} (Infraction #{total_points})")
            elif total_points >= cfg.timeout_threshold:
                action_taken = "Timeout (10m)"
                await member.timeout(timedelta(minutes=10), reason=f"[Automod Escalation] {reason} (Infraction #{total_points})")
            else:
                action_taken = "Warn"
                try:
                    await member.send(f"⚠️ **Automod Warning** in **{guild.name}**: {reason}. (Strike #{total_points})")
                except Exception:
                    pass
        except discord.Forbidden:
            logger.warning(f"Failed to apply {action_taken} to {member} in {guild.name} due to hierarchy/permissions.")

        await log_action(
            guild,
            title=f"Automod Action: {action_taken}",
            description=f"User: {member.mention} (`{member.id}`)\nReason: **{reason}**\nTotal Strikes: `{total_points}`",
            color=ERROR_COLOR if action_taken in ["Ban", "Kick"] else WARNING_COLOR
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        member = message.author
        if not isinstance(member, discord.Member):
            return

        # Bypass for administrators / owners
        if member.guild_permissions.administrator or member.id == message.guild.owner_id:
            return

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(AutomodConfig).where(AutomodConfig.guild_id == message.guild.id))
            cfg = res.scalar_one_or_none()

            if not cfg or not cfg.enabled:
                return

            # 1. Invite Link Filter
            if cfg.block_invites and INVITE_REGEX.search(message.content):
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                await self._escalate_action(message, "Posted unauthorized Discord invite link", cfg)
                return

            # 2. Mass Mention Filter
            if cfg.mass_mention_limit and (len(message.mentions) + len(message.role_mentions)) >= cfg.mass_mention_limit:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                await self._escalate_action(message, f"Mass mentions ({len(message.mentions) + len(message.role_mentions)} mentions)", cfg)
                return

            # 3. Profanity / Banned Words Filter
            banned_words = cfg.banned_words
            if banned_words:
                content_lower = message.content.lower()
                for word in banned_words:
                    if word.lower() in content_lower:
                        try:
                            await message.delete()
                        except discord.Forbidden:
                            pass
                        await self._escalate_action(message, f"Used blacklisted term: `{word}`", cfg)
                        return

            # 4. Spam Rate Limit (e.g. > N messages in 5 seconds)
            now = time.time()
            user_history = self.spam_tracker[message.guild.id][member.id]
            user_history.append(now)
            # Filter timestamps within last 5 seconds
            user_history = [t for t in user_history if now - t <= 5]
            self.spam_tracker[message.guild.id][member.id] = user_history

            if len(user_history) >= cfg.spam_threshold:
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                # Reset history to avoid re-triggering immediately
                self.spam_tracker[message.guild.id][member.id] = []
                await self._escalate_action(message, f"Spam detected ({len(user_history)} msgs in 5s)", cfg)
                return

    automod_group = app_commands.Group(name="automod", description="Configure Automod filters and escalation")

    @automod_group.command(name="status", description="View current automod settings and thresholds")
    @is_mod_or_has_role()
    async def automod_status(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(AutomodConfig).where(AutomodConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                return await interaction.response.send_message(
                    embed=info_embed("Automod Status", "Automod is not enabled on this server. Run `/automod toggle` to enable."),
                    ephemeral=True
                )

            embed = ego_embed(
                title="🛡️ Automod Configuration Panel",
                description=f"Status: **{'Enabled' if cfg.enabled else 'Disabled'}**",
                color=0x5865F2
            )
            embed.add_field(name="Invite Filter", value="Enabled" if cfg.block_invites else "Disabled", inline=True)
            embed.add_field(name="Spam Threshold", value=f"`{cfg.spam_threshold}` msgs / 5s", inline=True)
            embed.add_field(name="Mass Mentions", value=f"`{cfg.mass_mention_limit}` mentions", inline=True)
            embed.add_field(
                name="Escalation Ladder",
                value=(
                    f"• **Warn:** `{cfg.warn_threshold}` strikes\n"
                    f"• **Timeout (10m):** `{cfg.timeout_threshold}` strikes\n"
                    f"• **Kick:** `{cfg.kick_threshold}` strikes\n"
                    f"• **Ban:** `{cfg.ban_threshold}` strikes"
                ),
                inline=False
            )
            embed.add_field(
                name=f"Blacklisted Words ({len(cfg.banned_words)})",
                value=", ".join(f"`{w}`" for w in cfg.banned_words[:15]) if cfg.banned_words else "*None*",
                inline=False
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="toggle", description="Enable or disable automod")
    @is_admin_or_has_role()
    async def automod_toggle(self, interaction: discord.Interaction, enabled: bool):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(AutomodConfig).where(AutomodConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = AutomodConfig(guild_id=interaction.guild_id, enabled=enabled)
                session.add(cfg)
            else:
                cfg.enabled = enabled
            await session.commit()

        status_str = "Enabled" if enabled else "Disabled"
        await interaction.response.send_message(embed=success_embed("Automod Updated", f"Automod is now **{status_str}**."))
        await log_action(interaction.guild, title=f"Automod {status_str}", description=f"Automod status changed to {status_str}", moderator=interaction.user)

    @automod_group.command(name="set_thresholds", description="Configure automod filter thresholds")
    @app_commands.describe(
        spam_threshold="Max messages in 5s before spam trigger",
        mass_mentions="Max mentions allowed per message",
        block_invites="Block discord invite links (True/False)"
    )
    @is_admin_or_has_role()
    async def automod_set_thresholds(
        self,
        interaction: discord.Interaction,
        spam_threshold: Optional[int] = None,
        mass_mentions: Optional[int] = None,
        block_invites: Optional[bool] = None
    ):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(AutomodConfig).where(AutomodConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = AutomodConfig(guild_id=interaction.guild_id, enabled=True)
                session.add(cfg)

            if spam_threshold is not None:
                cfg.spam_threshold = spam_threshold
            if mass_mentions is not None:
                cfg.mass_mention_limit = mass_mentions
            if block_invites is not None:
                cfg.block_invites = block_invites

            await session.commit()

        await interaction.response.send_message(embed=success_embed("Thresholds Updated", "Automod filter limits have been updated."))
        await log_action(interaction.guild, title="Automod Thresholds Updated", description="Updated spam / mention / invite settings", moderator=interaction.user)

    @automod_group.command(name="add_word", description="Add a word to the automod blacklist")
    @app_commands.describe(word="Word or phrase to blacklist")
    @is_admin_or_has_role()
    async def automod_add_word(self, interaction: discord.Interaction, word: str):
        word = word.strip().lower()
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(AutomodConfig).where(AutomodConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = AutomodConfig(guild_id=interaction.guild_id, enabled=True)
                session.add(cfg)

            words = list(cfg.banned_words)
            if word not in words:
                words.append(word)
                cfg.banned_words = words
                await session.commit()

        await interaction.response.send_message(embed=success_embed("Word Blacklisted", f"Added `{word}` to blacklisted words."))

    @automod_group.command(name="remove_word", description="Remove a word from the automod blacklist")
    @app_commands.describe(word="Word or phrase to remove")
    @is_admin_or_has_role()
    async def automod_remove_word(self, interaction: discord.Interaction, word: str):
        word = word.strip().lower()
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(AutomodConfig).where(AutomodConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                return await interaction.response.send_message(embed=error_embed("Not Configured", "No automod config found."), ephemeral=True)

            words = list(cfg.banned_words)
            if word in words:
                words.remove(word)
                cfg.banned_words = words
                await session.commit()
                await interaction.response.send_message(embed=success_embed("Word Removed", f"Removed `{word}` from blacklist."))
            else:
                await interaction.response.send_message(embed=error_embed("Not Found", f"`{word}` was not in the blacklist."), ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AutomodCog(bot))
