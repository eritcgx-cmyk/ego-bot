"""
Comprehensive Invite Tracking, Tier Level Rewards, and Live Auto-Updating Leaderboard Cog for Ego Bot.
Features:
- Real-time join/leave tracking with fake account detection
- Automatic milestone tier role rewards & demotions
- Live auto-updating persistent Invite Leaderboard embed with interactive buttons
- Public /invites suite & Staff /invites_admin control suite
"""
import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select, desc
from database.engine import AsyncSessionLocal
from database.models import UserInviteStat, InviteTier
from utils.permissions import is_admin_or_has_role, is_guild_owner
from utils.embeds import (
    ego_embed, success_embed, error_embed, info_embed, card_embed,
    COLOR_VIOLET, COLOR_EMERALD, COLOR_AMBER, COLOR_CYAN, COLOR_ROSE, get_eastern_time
)
from config import INFO_COLOR, SUCCESS_COLOR, EMBED_COLOR, logger

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
BOARD_CONFIG_FILE = os.path.join(DATA_DIR, "invite_board_config.json")
INVITERS_MAP_FILE = os.path.join(DATA_DIR, "member_inviters.json")

def ensure_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(BOARD_CONFIG_FILE):
        with open(BOARD_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)
    if not os.path.exists(INVITERS_MAP_FILE):
        with open(INVITERS_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)

def load_board_configs() -> Dict[str, Any]:
    ensure_files()
    try:
        with open(BOARD_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_board_configs(data: Dict[str, Any]):
    ensure_files()
    with open(BOARD_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_inviters_map() -> Dict[str, int]:
    ensure_files()
    try:
        with open(INVITERS_MAP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_inviters_map(data: Dict[str, int]):
    ensure_files()
    with open(INVITERS_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class InviteLeaderboardView(discord.ui.View):
    """Persistent interactive view for the permanent Invite Leaderboard."""
    def __init__(self, cog: Optional["InvitesCog"] = None):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="inviteboard_btn_refresh")
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("❌ Server context missing.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        cog = self.cog or interaction.client.get_cog("Invites")
        if cog:
            await cog.update_guild_leaderboard(guild)
            await interaction.followup.send("✅ Invite Leaderboard refreshed with latest live data.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Internal error loading Invites module.", ephemeral=True)

    @discord.ui.button(label="My Stats", style=discord.ButtonStyle.primary, emoji="📊", custom_id="inviteboard_btn_mystats")
    async def mystats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        guild = interaction.guild
        if not guild:
            return

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(UserInviteStat).where(
                    UserInviteStat.guild_id == guild.id,
                    UserInviteStat.user_id == user.id
                )
            )
            stat = res.scalar_one_or_none()

            res_tiers = await session.execute(
                select(InviteTier).where(InviteTier.guild_id == guild.id).order_by(InviteTier.threshold.asc())
            )
            tiers = res_tiers.scalars().all()

        regular = stat.regular if stat else 0
        left = stat.left if stat else 0
        fake = stat.fake if stat else 0
        bonus = stat.bonus if stat else 0
        total = max(0, (regular + bonus) - (left + fake))

        # Check current and next tier
        current_tier_str = "None"
        next_tier_str = "All Tiers Completed 🎉"
        for t in tiers:
            if total >= t.threshold:
                role = guild.get_role(t.role_id) if t.role_id else None
                current_tier_str = f"Tier {t.tier_number} ({role.mention if role else 'Role'})"
            elif next_tier_str.startswith("All"):
                needed = t.threshold - total
                role = guild.get_role(t.role_id) if t.role_id else None
                next_tier_str = f"Tier {t.tier_number} ({t.threshold} invites) — **{needed}** more needed!"
                break

        embed = ego_embed(
            title=f"📈 Your Invite Progress: {user.display_name}",
            description=(
                f"> **Total Valid Invites:** `🌟 {total}`\n\n"
                f"**✦ Breakdown:**\n"
                f"• Regular Joins: `+{regular}`\n"
                f"• Members Left: `-{left}`\n"
                f"• Fake / Underage Accounts: `-{fake}`\n"
                f"• Staff Bonus: `+{bonus}`\n\n"
                f"**✦ Milestone Status:**\n"
                f"• Current Rank: {current_tier_str}\n"
                f"• Next Milestone: {next_tier_str}"
            ),
            color=COLOR_VIOLET
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="View Rewards", style=discord.ButtonStyle.secondary, emoji="🎁", custom_id="inviteboard_btn_tiers")
    async def tiers_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            return

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(InviteTier).where(InviteTier.guild_id == guild.id).order_by(InviteTier.tier_number.asc())
            )
            tiers = res.scalars().all()

        if not tiers:
            return await interaction.response.send_message(
                embed=info_embed("Invite Rewards", "No milestone reward tiers configured yet."),
                ephemeral=True
            )

        embed = ego_embed(
            title="🎁 Server Invite Reward Tiers",
            description="Invite friends to unlock permanent exclusive server ranks:\n",
            color=COLOR_AMBER
        )
        for t in tiers:
            role = guild.get_role(t.role_id) if t.role_id else None
            role_name = role.mention if role else "*No role assigned*"
            embed.add_field(
                name=f"› Tier {t.tier_number} — {t.threshold} Invites",
                value=f"• Reward Role: {role_name}",
                inline=True
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class InvitesCog(commands.Cog, name="Invites"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        ensure_files()
        self.invites_cache: Dict[int, Dict[str, int]] = {}
        self.leaderboard_loop.start()

    def cog_unload(self):
        self.leaderboard_loop.cancel()

    async def build_initial_cache(self):
        """Builds local invite tracking cache across all guilds."""
        for guild in self.bot.guilds:
            try:
                invites = await guild.invites()
                self.invites_cache[guild.id] = {inv.code: inv.uses for inv in invites if inv.uses is not None}
            except discord.Forbidden:
                pass
            except Exception as e:
                logger.debug(f"Could not cache invites for guild {guild.id}: {e}")
        logger.info("Cached guild invites.")

    @commands.Cog.listener()
    async def on_ready(self):
        await self.build_initial_cache()

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild and invite.uses is not None:
            if invite.guild.id not in self.invites_cache:
                self.invites_cache[invite.guild.id] = {}
            self.invites_cache[invite.guild.id][invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild and invite.guild.id in self.invites_cache:
            self.invites_cache[invite.guild.id].pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot or not member.guild:
            return

        guild = member.guild
        inviter: Optional[discord.User | discord.Member] = None

        try:
            cached_invites = self.invites_cache.get(guild.id, {})
            current_invites = await guild.invites()

            for inv in current_invites:
                if inv.uses is not None:
                    old_uses = cached_invites.get(inv.code, 0)
                    if inv.uses > old_uses:
                        inviter = inv.inviter
                        break

            # Update cache
            self.invites_cache[guild.id] = {inv.code: inv.uses for inv in current_invites if inv.uses is not None}
        except discord.Forbidden:
            pass

        if inviter and inviter.id != member.id:
            # Map member to inviter for leave tracking
            inv_map = load_inviters_map()
            inv_map[f"{guild.id}_{member.id}"] = inviter.id
            save_inviters_map(inv_map)

            # Check if account is fake (< 3 days old)
            account_age_days = (datetime.now(timezone.utc) - member.created_at).days
            is_fake = account_age_days < 3

            async with AsyncSessionLocal() as session:
                res = await session.execute(
                    select(UserInviteStat).where(
                        UserInviteStat.guild_id == guild.id,
                        UserInviteStat.user_id == inviter.id
                    )
                )
                stat = res.scalar_one_or_none()

                if not stat:
                    stat = UserInviteStat(
                        guild_id=guild.id,
                        user_id=inviter.id,
                        regular=1 if not is_fake else 0,
                        fake=1 if is_fake else 0
                    )
                    session.add(stat)
                else:
                    if is_fake:
                        stat.fake += 1
                    else:
                        stat.regular += 1

                await session.commit()

                # Check invite tiers and auto-grant roles
                inviter_member = guild.get_member(inviter.id)
                if inviter_member:
                    total = stat.total
                    res_tiers = await session.execute(
                        select(InviteTier).where(InviteTier.guild_id == guild.id, InviteTier.threshold <= total)
                    )
                    qualifying_tiers = res_tiers.scalars().all()
                    for tier in qualifying_tiers:
                        if tier.role_id:
                            r = guild.get_role(tier.role_id)
                            if r and r not in inviter_member.roles:
                                try:
                                    await inviter_member.add_roles(
                                        r,
                                        reason=f"Reached Invite Tier {tier.tier_number} ({tier.threshold} invites)"
                                    )
                                except Exception:
                                    pass

            # Trigger live leaderboard update
            await self.update_guild_leaderboard(guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot or not member.guild:
            return

        guild = member.guild
        inv_map = load_inviters_map()
        key = f"{guild.id}_{member.id}"
        inviter_id = inv_map.pop(key, None)
        save_inviters_map(inv_map)

        if inviter_id:
            async with AsyncSessionLocal() as session:
                res = await session.execute(
                    select(UserInviteStat).where(
                        UserInviteStat.guild_id == guild.id,
                        UserInviteStat.user_id == inviter_id
                    )
                )
                stat = res.scalar_one_or_none()
                if stat:
                    stat.left += 1
                    await session.commit()

                    # Check if inviter fell below a tier and remove role if necessary
                    inviter_member = guild.get_member(inviter_id)
                    if inviter_member:
                        total = stat.total
                        res_tiers = await session.execute(
                            select(InviteTier).where(InviteTier.guild_id == guild.id, InviteTier.threshold > total)
                        )
                        lost_tiers = res_tiers.scalars().all()
                        for tier in lost_tiers:
                            if tier.role_id:
                                r = guild.get_role(tier.role_id)
                                if r and r in inviter_member.roles:
                                    try:
                                        await inviter_member.remove_roles(
                                            r,
                                            reason=f"Dropped below Invite Tier {tier.tier_number} ({tier.threshold} invites)"
                                        )
                                    except Exception:
                                        pass

            # Trigger live leaderboard update
            await self.update_guild_leaderboard(guild)

    async def build_leaderboard_embed(self, guild: discord.Guild) -> discord.Embed:
        """Constructs an aesthetic, rich, full leaderboard embed."""
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(UserInviteStat)
                .where(UserInviteStat.guild_id == guild.id)
                .order_by(desc(UserInviteStat.regular + UserInviteStat.bonus - UserInviteStat.left - UserInviteStat.fake))
                .limit(15)
            )
            top_stats = res.scalars().all()

        total_trackable = len(top_stats)
        medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10.", "11.", "12.", "13.", "14.", "15."]

        embed = ego_embed(
            title=f"🏆 Top Server Inviters • {guild.name}",
            description=(
                f"> **Server Roster:** `{guild.member_count:,}` members\n"
                f"> **Active Inviters Tracked:** `{total_trackable}`\n\n"
                f"✦ **Official Server Leaderboard:**\n"
            ),
            color=COLOR_VIOLET
        )

        if not top_stats:
            embed.description += "*No invites recorded yet. Share your invite links to get on the board!*"
        else:
            lines = []
            for i, s in enumerate(top_stats):
                prefix = medals[i] if i < len(medals) else f"**{i+1}.**"
                member = guild.get_member(s.user_id)
                user_tag = member.mention if member else f"`User {s.user_id}`"
                lines.append(
                    f"{prefix} {user_tag} — **`{s.total}`** invites `(+{s.regular} reg, -{s.left} left, +{s.bonus} bns)`"
                )
            embed.description += "\n".join(lines)

        embed.set_footer(
            text=f"Ego Invite System • Live Event Sync • {get_eastern_time()}",
            icon_url=guild.icon.url if guild.icon else None
        )
        return embed

    async def update_guild_leaderboard(self, guild: discord.Guild):
        """Updates the posted permanent leaderboard message for a guild."""
        cfg = load_board_configs()
        g_data = cfg.get(str(guild.id))
        if not g_data or not g_data.get("channel_id") or not g_data.get("message_id"):
            return

        try:
            channel = guild.get_channel(g_data["channel_id"])
            if channel and isinstance(channel, discord.TextChannel):
                msg = await channel.fetch_message(g_data["message_id"])
                if msg:
                    embed = await self.build_leaderboard_embed(guild)
                    view = InviteLeaderboardView(cog=self)
                    await msg.edit(embed=embed, view=view)
        except discord.NotFound:
            pass
        except Exception as e:
            logger.debug(f"Could not auto-update invite leaderboard for guild {guild.id}: {e}")

    @tasks.loop(minutes=5)
    async def leaderboard_loop(self):
        """Periodic background refresh loop for all permanent leaderboards."""
        for guild in self.bot.guilds:
            try:
                await self.update_guild_leaderboard(guild)
            except Exception as e:
                logger.debug(f"Error in leaderboard background loop for guild {guild.id}: {e}")

    @leaderboard_loop.before_loop
    async def before_leaderboard_loop(self):
        await self.bot.wait_until_ready()

    # =========================================================================
    # PUBLIC MEMBER SLASH COMMAND GROUP (/invites)
    # =========================================================================
    invites_group = app_commands.Group(name="invites", description="Invite tracking, leaderboards, and statistics")

    @invites_group.command(name="mystats", description="Check your personal or another member's invite statistics")
    @app_commands.describe(user="User to check stats for (defaults to yourself)")
    async def invites_mystats(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("❌ Must be run in a server.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(UserInviteStat).where(
                    UserInviteStat.guild_id == guild.id,
                    UserInviteStat.user_id == target.id
                )
            )
            stat = res.scalar_one_or_none()

            res_tiers = await session.execute(
                select(InviteTier).where(InviteTier.guild_id == guild.id).order_by(InviteTier.threshold.asc())
            )
            tiers = res_tiers.scalars().all()

        regular = stat.regular if stat else 0
        left = stat.left if stat else 0
        fake = stat.fake if stat else 0
        bonus = stat.bonus if stat else 0
        total = max(0, (regular + bonus) - (left + fake))

        # Check current and next tier
        current_tier_str = "None"
        next_tier_str = "All Tiers Completed 🎉"
        for t in tiers:
            if total >= t.threshold:
                role = guild.get_role(t.role_id) if t.role_id else None
                current_tier_str = f"Tier {t.tier_number} ({role.mention if role else 'Role'})"
            elif next_tier_str.startswith("All"):
                needed = t.threshold - total
                role = guild.get_role(t.role_id) if t.role_id else None
                next_tier_str = f"Tier {t.tier_number} ({t.threshold} invites) — **{needed}** more needed!"
                break

        embed = ego_embed(
            title=f"📈 Invite Statistics: {target.display_name}",
            description=(
                f"> **Total Valid Invites:** `🌟 {total}`\n\n"
                f"**✦ Activity Breakdown:**\n"
                f"• Regular Joins: `+{regular}`\n"
                f"• Members Left: `-{left}`\n"
                f"• Fake / Underage Accounts: `-{fake}`\n"
                f"• Staff Bonus: `+{bonus}`\n\n"
                f"**✦ Reward Status:**\n"
                f"• Current Tier: {current_tier_str}\n"
                f"• Next Milestone: {next_tier_str}"
            ),
            color=COLOR_VIOLET
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @invites_group.command(name="leaderboard", description="View server top inviters ranking")
    async def invites_leaderboard(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("❌ Must be run in a server.", ephemeral=True)

        embed = await self.build_leaderboard_embed(guild)
        view = InviteLeaderboardView(cog=self)
        await interaction.response.send_message(embed=embed, view=view)

    @invites_group.command(name="tiers", description="View all server milestone reward tiers")
    async def invites_tiers_public(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(InviteTier).where(InviteTier.guild_id == guild.id).order_by(InviteTier.tier_number.asc())
            )
            tiers = res.scalars().all()

        if not tiers:
            return await interaction.response.send_message(
                embed=info_embed("Invite Rewards", "No milestone reward tiers configured yet."),
                ephemeral=True
            )

        embed = ego_embed(
            title="🎁 Server Invite Reward Tiers",
            description="Invite friends to unlock permanent exclusive server ranks:\n",
            color=COLOR_AMBER
        )
        for t in tiers:
            role = guild.get_role(t.role_id) if t.role_id else None
            role_name = role.mention if role else "*No role assigned*"
            embed.add_field(
                name=f"› Tier {t.tier_number} — {t.threshold} Invites",
                value=f"• Reward Role: {role_name}",
                inline=True
            )

        await interaction.response.send_message(embed=embed)

    # =========================================================================
    # STAFF / ADMIN CONTROL GROUP (/invites_admin)
    # =========================================================================
    invites_admin_group = app_commands.Group(
        name="invites_admin",
        description="Staff administration controls for invite tracking and leaderboards",
        default_permissions=discord.Permissions(manage_roles=True)
    )

    @invites_admin_group.command(name="post_leaderboard", description="Deploy a permanent, auto-updating Invite Leaderboard to a channel")
    @app_commands.describe(channel="Channel to deploy the permanent leaderboard in (defaults to current)")
    @is_admin_or_has_role()
    async def invites_admin_post_board(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target_ch = channel or interaction.channel
        guild = interaction.guild
        if not guild or not target_ch:
            return await interaction.response.send_message("❌ Channel not found.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        embed = await self.build_leaderboard_embed(guild)
        view = InviteLeaderboardView(cog=self)
        msg = await target_ch.send(embed=embed, view=view)

        # Save config for auto-updating
        cfg = load_board_configs()
        cfg[str(guild.id)] = {
            "channel_id": target_ch.id,
            "message_id": msg.id,
            "deployed_at": datetime.now(timezone.utc).isoformat()
        }
        save_board_configs(cfg)

        await interaction.followup.send(
            embed=success_embed(
                "Leaderboard Deployed",
                f"✅ Live auto-updating Invite Leaderboard is active in {target_ch.mention}.\n"
                f"• Updates automatically on every join, leave, and every 5 minutes.\n"
                f"• Members can click **[My Stats]** or **[View Rewards]** anytime."
            ),
            ephemeral=True
        )

    @invites_admin_group.command(name="config_tier", description="Configure an invite tier reward role (1 through 10)")
    @app_commands.describe(
        tier_number="Tier number (1-10)",
        threshold="Invite count required",
        role="Role to grant upon reaching threshold"
    )
    @is_admin_or_has_role()
    async def invites_config_tier(
        self,
        interaction: discord.Interaction,
        tier_number: int,
        threshold: int,
        role: discord.Role
    ):
        if not (1 <= tier_number <= 10):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Tier", "Tier number must be between 1 and 10."),
                ephemeral=True
            )

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(InviteTier).where(
                    InviteTier.guild_id == interaction.guild_id,
                    InviteTier.tier_number == tier_number
                )
            )
            tier = res.scalar_one_or_none()

            if not tier:
                tier = InviteTier(
                    guild_id=interaction.guild_id,
                    tier_number=tier_number,
                    threshold=threshold,
                    role_id=role.id
                )
                session.add(tier)
            else:
                tier.threshold = threshold
                tier.role_id = role.id

            await session.commit()

        await interaction.response.send_message(
            embed=success_embed(
                "Invite Tier Configured",
                f"**Tier {tier_number}** set to `{threshold}` invites $\\rightarrow$ {role.mention}."
            )
        )

    @invites_admin_group.command(name="add_bonus", description="Grant bonus invites to a member")
    @app_commands.describe(
        user="Member to receive bonus invites",
        amount="Amount of bonus invites to grant",
        reason="Reason for granting bonus"
    )
    @is_admin_or_has_role()
    async def invites_admin_bonus(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: int,
        reason: Optional[str] = "Staff Bonus"
    ):
        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(UserInviteStat).where(
                    UserInviteStat.guild_id == guild.id,
                    UserInviteStat.user_id == user.id
                )
            )
            stat = res.scalar_one_or_none()
            if not stat:
                stat = UserInviteStat(guild_id=guild.id, user_id=user.id, bonus=amount)
                session.add(stat)
            else:
                stat.bonus += amount

            await session.commit()

            # Check tier upgrades
            total = stat.total
            res_tiers = await session.execute(
                select(InviteTier).where(InviteTier.guild_id == guild.id, InviteTier.threshold <= total)
            )
            qualifying_tiers = res_tiers.scalars().all()
            for tier in qualifying_tiers:
                if tier.role_id:
                    r = guild.get_role(tier.role_id)
                    if r and r not in user.roles:
                        try:
                            await user.add_roles(r, reason=f"Reached Tier {tier.tier_number} via Bonus Invites")
                        except Exception:
                            pass

        await self.update_guild_leaderboard(guild)
        await interaction.response.send_message(
            embed=success_embed(
                "Bonus Invites Added",
                f"Added **`+{amount}`** bonus invites to {user.mention} (New Total: `{total}`).\nReason: *{reason}*"
            )
        )

    @invites_admin_group.command(name="reset_user", description="Reset a member's tracked invite statistics")
    @app_commands.describe(user="Member whose stats will be reset")
    @is_guild_owner()
    async def invites_admin_reset(self, interaction: discord.Interaction, user: discord.Member):
        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(UserInviteStat).where(
                    UserInviteStat.guild_id == guild.id,
                    UserInviteStat.user_id == user.id
                )
            )
            stat = res.scalar_one_or_none()
            if stat:
                stat.regular = 0
                stat.left = 0
                stat.fake = 0
                stat.bonus = 0
                await session.commit()

        await self.update_guild_leaderboard(guild)
        await interaction.response.send_message(
            embed=success_embed("Stats Reset", f"Reset all tracked invite records for {user.mention}."),
            ephemeral=True
        )

    @invites_admin_group.command(name="panel", description="Post a summary panel of all invite reward tiers")
    async def invites_panel(self, interaction: discord.Interaction):
        guild = interaction.guild
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(InviteTier)
                .where(InviteTier.guild_id == guild.id)
                .order_by(InviteTier.tier_number.asc())
            )
            tiers = res.scalars().all()

        if not tiers:
            return await interaction.response.send_message(
                embed=info_embed("Invite Tiers", "No invite tiers configured yet. Run `/invites_admin config_tier`."),
                ephemeral=True
            )

        embed = ego_embed(
            title="🎁 Server Invite Rewards",
            description="Invite your friends to earn exclusive server ranks!",
            color=INFO_COLOR
        )
        for t in tiers:
            r = guild.get_role(t.role_id) if t.role_id else None
            role_name = r.mention if r else "*No role assigned*"
            embed.add_field(
                name=f"Tier {t.tier_number} ({t.threshold} Invites)",
                value=f"Reward: {role_name}",
                inline=True
            )

        await interaction.response.send_message(embed=embed)

    # =========================================================================
    # TOP-LEVEL CONVENIENCE ALIASES FOR LEADERBOARD POSTING
    # =========================================================================
    @app_commands.command(name="invite_board", description="Deploy the permanent auto-updating Invite Leaderboard to a channel")
    @app_commands.describe(channel="Target channel (optional)")
    @app_commands.default_permissions(manage_guild=True)
    @is_admin_or_has_role()
    async def invite_board_alias(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await self.invites_admin_post_board(interaction, channel)

    @app_commands.command(name="inviteboard", description="Deploy the permanent auto-updating Invite Leaderboard (alias)")
    @app_commands.describe(channel="Target channel (optional)")
    @app_commands.default_permissions(manage_guild=True)
    @is_admin_or_has_role()
    async def inviteboard_alias(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        await self.invites_admin_post_board(interaction, channel)


async def setup(bot: commands.Bot):
    cog = InvitesCog(bot)
    await bot.add_cog(cog)
