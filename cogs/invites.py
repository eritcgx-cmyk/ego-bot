"""
Invite Tracking and Level Rewards Cog for Ego Bot
"""
from typing import Optional, Dict, List
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, desc
from database.engine import AsyncSessionLocal
from database.models import UserInviteStat, InviteTier
from utils.permissions import is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import INFO_COLOR, SUCCESS_COLOR, logger

class InvitesCog(commands.Cog, name="Invites"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Invite cache: {guild_id: {invite_code: uses}}
        self.invites_cache: Dict[int, Dict[str, int]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        """Build initial invite cache for all accessible guilds."""
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
                        cached_invites[inv.code] = inv.uses
                        break

            # Update cache
            self.invites_cache[guild.id] = {inv.code: inv.uses for inv in current_invites if inv.uses is not None}
        except discord.Forbidden:
            pass

        if inviter and inviter.id != member.id:
            async with AsyncSessionLocal() as session:
                res = await session.execute(
                    select(UserInviteStat).where(
                        UserInviteStat.guild_id == guild.id,
                        UserInviteStat.user_id == inviter.id
                    )
                )
                stat = res.scalar_one_or_none()

                if not stat:
                    stat = UserInviteStat(guild_id=guild.id, user_id=inviter.id, regular=1)
                    session.add(stat)
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
                                    await inviter_member.add_roles(r, reason=f"Reached Invite Tier {tier.tier_number} ({tier.threshold} invites)")
                                except Exception:
                                    pass

    invites_group = app_commands.Group(name="invites", description="Invite tracking, leaderboards, and statistics")
    invites_admin_group = app_commands.Group(
        name="invites_admin",
        description="Staff administration controls for invite tiers",
        default_permissions=discord.Permissions(manage_roles=True)
    )

    @invites_group.command(name="mystats", description="Check your personal invite statistics")
    @app_commands.describe(user="User to check stats for (default yourself)")
    async def invites_mystats(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(UserInviteStat).where(
                    UserInviteStat.guild_id == interaction.guild_id,
                    UserInviteStat.user_id == target.id
                )
            )
            stat = res.scalar_one_or_none()

        regular = stat.regular if stat else 0
        left = stat.left if stat else 0
        fake = stat.fake if stat else 0
        bonus = stat.bonus if stat else 0
        total = max(0, (regular + bonus) - (left + fake))

        embed = ego_embed(
            title=f"📈 Invite Statistics: {target.display_name}",
            description=(
                f"**Total Valid Invites:** `{total}`\n\n"
                f"• Regular: `{regular}`\n"
                f"• Left: `{left}`\n"
                f"• Fake: `{fake}`\n"
                f"• Bonus: `{bonus}`"
            ),
            color=INFO_COLOR
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @invites_group.command(name="leaderboard", description="View server top inviters")
    async def invites_leaderboard(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(UserInviteStat)
                .where(UserInviteStat.guild_id == interaction.guild_id)
                .order_by(desc(UserInviteStat.regular + UserInviteStat.bonus - UserInviteStat.left - UserInviteStat.fake))
                .limit(10)
            )
            top_stats = res.scalars().all()

        if not top_stats:
            return await interaction.response.send_message(
                embed=info_embed("Invite Leaderboard", "No recorded invites in this server yet."),
                ephemeral=True
            )

        embed = ego_embed(title="🏆 Top Server Inviters", color=SUCCESS_COLOR)
        lines = []
        for i, s in enumerate(top_stats, 1):
            member = interaction.guild.get_member(s.user_id)
            name = member.mention if member else f"`User {s.user_id}`"
            lines.append(f"**#{i}** {name} — **{s.total}** invites (`{s.regular}` reg, `{s.left}` left)")

        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

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

    @invites_admin_group.command(name="panel", description="Post a summary panel of all invite reward tiers")
    async def invites_panel(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(InviteTier)
                .where(InviteTier.guild_id == interaction.guild_id)
                .order_by(InviteTier.tier_number.asc())
            )
            tiers = res.scalars().all()

        if not tiers:
            return await interaction.response.send_message(
                embed=info_embed("Invite Tiers", "No invite tiers configured yet. Run `/invites config_tier`."),
                ephemeral=True
            )

        embed = ego_embed(
            title="🎁 Server Invite Rewards",
            description="Invite your friends to earn exclusive server ranks!",
            color=INFO_COLOR
        )
        for t in tiers:
            r = interaction.guild.get_role(t.role_id) if t.role_id else None
            role_name = r.mention if r else "*No role assigned*"
            embed.add_field(
                name=f"Tier {t.tier_number} ({t.threshold} Invites)",
                value=f"Reward: {role_name}",
                inline=True
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(InvitesCog(bot))

