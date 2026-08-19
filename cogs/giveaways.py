"""
Giveaways System Cog for Ego Bot
"""
import re
import random
from datetime import datetime, timedelta
from typing import Optional, List
import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import Giveaway
from utils.permissions import is_mod_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, logger

def parse_duration(time_str: str) -> Optional[timedelta]:
    """Parse time string like 10m, 2h, 3d into timedelta."""
    time_str = time_str.strip().lower()
    match = re.match(r"^(\d+)([smhd])$", time_str)
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    if unit == "s":
        return timedelta(seconds=val)
    elif unit == "m":
        return timedelta(minutes=val)
    elif unit == "h":
        return timedelta(hours=val)
    elif unit == "d":
        return timedelta(days=val)
    return None

class GiveawayEntryView(discord.ui.View):
    def __init__(self, giveaway_id: int):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        # Custom ID for persistence across bot reboots
        self.entry_button.custom_id = f"giveaway_entry:{giveaway_id}"

    @discord.ui.button(label="Enter Giveaway (0)", style=discord.ButtonStyle.primary, emoji="🎉")
    async def entry_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(Giveaway).where(Giveaway.id == self.giveaway_id))
            gw = res.scalar_one_or_none()

            if not gw or gw.status != "active":
                return await interaction.response.send_message("❌ This giveaway is no longer active.", ephemeral=True)

            if gw.required_role_id:
                member = interaction.user
                if isinstance(member, discord.Member) and not any(r.id == gw.required_role_id for r in member.roles):
                    req_role = interaction.guild.get_role(gw.required_role_id)
                    role_name = req_role.name if req_role else "Required Role"
                    return await interaction.response.send_message(
                        f"❌ You need the **{role_name}** role to enter this giveaway!",
                        ephemeral=True
                    )

            participants = list(gw.participants)
            if interaction.user.id in participants:
                participants.remove(interaction.user.id)
                gw.participants = participants
                await session.commit()
                button.label = f"Enter Giveaway ({len(participants)})"
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    pass
                return await interaction.response.send_message("📤 You have left the giveaway.", ephemeral=True)
            else:
                participants.append(interaction.user.id)
                gw.participants = participants
                await session.commit()
                button.label = f"Enter Giveaway ({len(participants)})"
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    pass
                return await interaction.response.send_message("🎉 You have entered the giveaway! Good luck!", ephemeral=True)

class GiveawaysCog(commands.Cog, name="Giveaways"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    async def restore_persistent_views(self):
        """Restore persistent buttons for all active giveaways."""
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(Giveaway).where(Giveaway.status == "active"))
            active_gws = res.scalars().all()
            for gw in active_gws:
                view = GiveawayEntryView(gw.id)
                # Update label with current participant count
                view.entry_button.label = f"Enter Giveaway ({len(gw.participants)})"
                self.bot.add_view(view, message_id=gw.message_id)
        logger.info("Restored persistent views for active giveaways.")

    @tasks.loop(seconds=10)
    async def check_giveaways(self):
        """Background task checking for ended giveaways."""
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(Giveaway).where(Giveaway.status == "active", Giveaway.end_time <= now)
            )
            ended_gws = res.scalars().all()

            for gw in ended_gws:
                await self._end_giveaway(session, gw)

    async def _end_giveaway(self, session, gw: Giveaway) -> None:
        """Internal helper to end giveaway and draw winners."""
        gw.status = "ended"
        participants = gw.participants
        winners = []
        if participants:
            count = min(gw.winners_count, len(participants))
            winners = random.sample(participants, count)
        gw.winners = winners
        await session.commit()

        guild = self.bot.get_guild(gw.guild_id)
        if not guild:
            return
        channel = guild.get_channel(gw.channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return

        try:
            msg = await channel.fetch_message(gw.message_id)
            if winners:
                winner_mentions = ", ".join(f"<@{w}>" for w in winners)
                embed = ego_embed(
                    title=f"🎉 Giveaway Ended: {gw.prize}",
                    description=f"**Winners:** {winner_mentions}\n**Hosted by:** <@{gw.host_id}>\n**Total Entries:** {len(participants)}",
                    color=SUCCESS_COLOR
                )
                await msg.edit(embed=embed, view=None)
                await channel.send(f"🎉 Congratulations {winner_mentions}! You won the **{gw.prize}**!")
            else:
                embed = ego_embed(
                    title=f"🎉 Giveaway Ended: {gw.prize}",
                    description=f"No valid entries were received.\n**Hosted by:** <@{gw.host_id}>",
                    color=ERROR_COLOR
                )
                await msg.edit(embed=embed, view=None)
                await channel.send(f"⚠️ Giveaway for **{gw.prize}** ended with no entries.")
        except Exception as e:
            logger.error(f"Error updating ended giveaway message {gw.id}: {e}")

    giveaway_group = app_commands.Group(name="giveaway", description="Manage server giveaways")

    @giveaway_group.command(name="start", description="Start a new giveaway")
    @app_commands.describe(
        prize="The prize to give away",
        duration="Duration (e.g. 30m, 2h, 1d)",
        winners="Number of winners (default 1)",
        required_role="Optional role required to enter",
        channel="Channel to post giveaway in (default current channel)"
    )
    @is_mod_or_has_role()
    async def giveaway_start(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winners: int = 1,
        required_role: Optional[discord.Role] = None,
        channel: Optional[discord.TextChannel] = None
    ):
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Channel", "Giveaways can only be hosted in text channels."),
                ephemeral=True
            )

        td = parse_duration(duration)
        if not td:
            return await interaction.response.send_message(
                embed=error_embed("Invalid Duration", "Use formats like `10m`, `2h`, `1d`."),
                ephemeral=True
            )

        end_time = datetime.utcnow() + td
        timestamp_code = f"<t:{int(end_time.timestamp())}:R>"

        embed = ego_embed(
            title=f"🎉 GIVEAWAY: {prize}",
            description=(
                f"Click the button below to enter!\n\n"
                f"⏰ **Ends:** {timestamp_code}\n"
                f"🏆 **Winners:** `{winners}`\n"
                f"👑 **Hosted by:** {interaction.user.mention}\n"
                + (f"🔒 **Required Role:** {required_role.mention}\n" if required_role else "")
            ),
            color=SUCCESS_COLOR
        )

        await interaction.response.send_message("Creating giveaway...", ephemeral=True)

        async with AsyncSessionLocal() as session:
            # Create preliminary DB entry
            gw = Giveaway(
                guild_id=interaction.guild_id,
                channel_id=target_channel.id,
                message_id=0,
                prize=prize,
                host_id=interaction.user.id,
                end_time=end_time,
                winners_count=winners,
                required_role_id=required_role.id if required_role else None,
                status="active"
            )
            session.add(gw)
            await session.commit()
            await session.refresh(gw)

            view = GiveawayEntryView(gw.id)
            msg = await target_channel.send(embed=embed, view=view)
            gw.message_id = msg.id
            await session.commit()

            self.bot.add_view(view, message_id=msg.id)

        await interaction.edit_original_response(content=f"✅ Giveaway started in {target_channel.mention}!")
        await log_action(
            interaction.guild,
            title="Giveaway Started",
            description=f"Prize: **{prize}** | Winners: `{winners}` | Channel: {target_channel.mention}",
            moderator=interaction.user
        )

    @giveaway_group.command(name="end", description="End an active giveaway early")
    @app_commands.describe(giveaway_id="ID of the giveaway to end")
    @is_mod_or_has_role()
    async def giveaway_end(self, interaction: discord.Interaction, giveaway_id: int):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(Giveaway).where(Giveaway.id == giveaway_id, Giveaway.guild_id == interaction.guild_id)
            )
            gw = res.scalar_one_or_none()
            if not gw:
                return await interaction.response.send_message(
                    embed=error_embed("Not Found", f"Giveaway #{giveaway_id} does not exist."),
                    ephemeral=True
                )
            if gw.status != "active":
                return await interaction.response.send_message(
                    embed=error_embed("Already Ended", f"Giveaway #{giveaway_id} is already `{gw.status}`."),
                    ephemeral=True
                )

            await self._end_giveaway(session, gw)
            await interaction.response.send_message(
                embed=success_embed("Giveaway Ended", f"Giveaway #{giveaway_id} ({gw.prize}) ended immediately.")
            )

    @giveaway_group.command(name="reroll", description="Reroll winners for an ended giveaway")
    @app_commands.describe(giveaway_id="ID of the giveaway to reroll", winners="Number of winners to pick")
    @is_mod_or_has_role()
    async def giveaway_reroll(self, interaction: discord.Interaction, giveaway_id: int, winners: int = 1):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(Giveaway).where(Giveaway.id == giveaway_id, Giveaway.guild_id == interaction.guild_id)
            )
            gw = res.scalar_one_or_none()
            if not gw:
                return await interaction.response.send_message(
                    embed=error_embed("Not Found", f"Giveaway #{giveaway_id} does not exist."),
                    ephemeral=True
                )

            participants = gw.participants
            if not participants:
                return await interaction.response.send_message(
                    embed=error_embed("No Entries", "No participants entered this giveaway to reroll from."),
                    ephemeral=True
                )

            count = min(winners, len(participants))
            new_winners = random.sample(participants, count)
            gw.winners = new_winners
            await session.commit()

            mentions = ", ".join(f"<@{w}>" for w in new_winners)
            channel = interaction.guild.get_channel(gw.channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                await channel.send(f"🎲 **Reroll!** New winner(s) for **{gw.prize}**: {mentions}!")

            await interaction.response.send_message(
                embed=success_embed("Giveaway Rerolled", f"Selected {mentions} as new winner(s).")
            )

    @app_commands.command(name="gwannounce", description="Re-broadcast or ping about an active giveaway")
    @app_commands.describe(
        giveaway_id="ID of the giveaway",
        channel="Channel to broadcast announcement in",
        ping_role="Optional role to ping"
    )
    @is_mod_or_has_role()
    async def gwannounce(
        self,
        interaction: discord.Interaction,
        giveaway_id: int,
        channel: discord.TextChannel,
        ping_role: Optional[discord.Role] = None
    ):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(Giveaway).where(Giveaway.id == giveaway_id, Giveaway.guild_id == interaction.guild_id)
            )
            gw = res.scalar_one_or_none()
            if not gw or gw.status != "active":
                return await interaction.response.send_message(
                    embed=error_embed("Active Giveaway Not Found", f"Giveaway #{giveaway_id} is not active."),
                    ephemeral=True
                )

            embed = ego_embed(
                title=f"📢 GIVEAWAY ALERT: {gw.prize}",
                description=(
                    f"An active giveaway is running right now!\n\n"
                    f"🎁 **Prize:** {gw.prize}\n"
                    f"⏰ **Ends:** <t:{int(gw.end_time.timestamp())}:R>\n"
                    f"🔗 **Jump to Giveaway:** [Click Here](https://discord.com/channels/{interaction.guild_id}/{gw.channel_id}/{gw.message_id})\n"
                ),
                color=INFO_COLOR
            )

            content = ping_role.mention if ping_role else None
            await channel.send(content=content, embed=embed)
            await interaction.response.send_message(
                embed=success_embed("Announced", f"Giveaway #{giveaway_id} broadcasted to {channel.mention}.")
            )

async def setup(bot: commands.Bot):
    cog = GiveawaysCog(bot)
    await bot.add_cog(cog)
    await cog.restore_persistent_views()
