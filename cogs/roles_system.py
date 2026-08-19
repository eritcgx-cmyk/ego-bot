"""
Role Preset and Perk System Cog for Ego Bot
"""
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import RolePerk, RolePanel
from utils.permissions import is_guild_owner, is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import SUCCESS_COLOR, INFO_COLOR, logger

PRESETS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "role_presets.json")

class RolesSystemCog(commands.Cog, name="RolesSystem"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.presets: List[Dict[str, Any]] = []
        self._load_presets()
        self.refresh_role_panels.start()

    def cog_unload(self):
        self.refresh_role_panels.cancel()

    def _load_presets(self):
        try:
            if os.path.exists(PRESETS_PATH):
                with open(PRESETS_PATH, "r", encoding="utf-8") as f:
                    self.presets = json.load(f)
                logger.info(f"Loaded {len(self.presets)} role presets.")
        except Exception as e:
            logger.error(f"Failed to load role presets: {e}")

    @tasks.loop(minutes=11)
    async def refresh_role_panels(self):
        """Auto-refresh role panels every 11 minutes across all servers."""
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(RolePanel))
            panels = res.scalars().all()

            for panel in panels:
                guild = self.bot.get_guild(panel.guild_id)
                if not guild:
                    continue
                channel = guild.get_channel(panel.channel_id)
                if not channel or not isinstance(channel, discord.TextChannel):
                    continue

                try:
                    msg = await channel.fetch_message(panel.message_id)
                    embed = await self._generate_panel_embed(guild, panel)
                    await msg.edit(embed=embed)
                    panel.last_refreshed = datetime.utcnow()
                except discord.NotFound:
                    # Message was deleted, remove panel from DB
                    await session.delete(panel)
                except Exception as e:
                    logger.debug(f"Error refreshing panel {panel.id}: {e}")

            await session.commit()

    @refresh_role_panels.before_loop
    async def before_refresh_role_panels(self):
        await self.bot.wait_until_ready()

    async def _generate_panel_embed(self, guild: discord.Guild, panel: RolePanel) -> discord.Embed:
        """Helper to build role roster embed."""
        embed = ego_embed(
            title=f"👑 Role Roster: {panel.category}",
            description="Live overview of member role distributions.\n*Updates automatically every 11 minutes.*",
            color=INFO_COLOR
        )

        role_ids = panel.role_ids
        for rid in role_ids[:20]: # Show up to 20 roles per panel
            role = guild.get_role(rid)
            if role:
                member_count = len(role.members)
                top_members = ", ".join(m.mention for m in role.members[:5])
                val = f"**Members ({member_count}):** {top_members}" if member_count > 0 else "*No members*"
                if member_count > 5:
                    val += f" *and {member_count - 5} more...*"
                embed.add_field(name=f"@{role.name}", value=val, inline=False)

        return embed

    roles_group = app_commands.Group(name="roles", description="Role library, presets, perks, and live panels")

    @roles_group.command(name="import_presets", description="Bulk import preset roles from catalog into server")
    @app_commands.describe(
        category="Category to import (Content Creator, Verified, Mod, Rich/Status, Custom)",
        count="Number of roles to import (max 15 at once to avoid rate limits)"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="Content Creator", value="Content Creator"),
        app_commands.Choice(name="Verified", value="Verified"),
        app_commands.Choice(name="Mod & Staff", value="Mod"),
        app_commands.Choice(name="Rich / Status", value="Rich/Status"),
        app_commands.Choice(name="Custom & Aesthetic", value="Custom")
    ])
    @is_guild_owner()
    async def roles_import_presets(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        count: int = 5
    ):
        await interaction.response.defer(ephemeral=True)
        count = max(1, min(count, 15))

        filtered = [p for p in self.presets if p["category"] == category.value]
        if not filtered:
            return await interaction.followup.send(embed=error_embed("No Presets", "No presets found for this category."))

        created_roles = []
        for preset in filtered[:count]:
            color_int = int(preset["color"].lstrip("#"), 16)
            try:
                role = await interaction.guild.create_role(
                    name=preset["name"],
                    color=discord.Color(color_int),
                    hoist=preset.get("hoist", False),
                    mentionable=preset.get("mentionable", False),
                    reason=f"Preset import ({category.value})"
                )
                created_roles.append(role)
            except Exception as e:
                logger.error(f"Failed to create preset role {preset['name']}: {e}")

        roles_str = ", ".join(r.mention for r in created_roles)
        await interaction.followup.send(
            embed=success_embed(
                "Presets Imported",
                f"Successfully created `{len(created_roles)}` roles from **{category.name}**:\n{roles_str}"
            )
        )
        await log_action(
            interaction.guild,
            title="Role Presets Imported",
            description=f"Imported {len(created_roles)} roles from {category.name}",
            moderator=interaction.user
        )

    @roles_group.command(name="create_custom", description="Create a custom role with full styling")
    @app_commands.describe(
        name="Role Name",
        hex_color="Hex color code (e.g. #FF007F)",
        hoist="Display role members separately in member list",
        mentionable="Allow anyone to mention this role"
    )
    @is_admin_or_has_role()
    async def roles_create_custom(
        self,
        interaction: discord.Interaction,
        name: str,
        hex_color: Optional[str] = "#5865F2",
        hoist: bool = False,
        mentionable: bool = False
    ):
        try:
            color_val = int(hex_color.lstrip("#"), 16)
        except ValueError:
            color_val = 0x5865F2

        try:
            role = await interaction.guild.create_role(
                name=name,
                color=discord.Color(color_val),
                hoist=hoist,
                mentionable=mentionable,
                reason="Custom role creation command"
            )
            await interaction.response.send_message(
                embed=success_embed("Role Created", f"Successfully created role {role.mention}!")
            )
        except Exception as e:
            await interaction.response.send_message(
                embed=error_embed("Failed to Create", f"Error: {e}"),
                ephemeral=True
            )

    @roles_group.command(name="perks", description="Configure perk flags for a role")
    @app_commands.describe(
        role="The target role",
        giveaway_access="Grant exclusive giveaway access",
        custom_color="Grant custom color permissions"
    )
    @is_admin_or_has_role()
    async def roles_perks(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        giveaway_access: Optional[bool] = None,
        custom_color: Optional[bool] = None
    ):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(RolePerk).where(RolePerk.guild_id == interaction.guild_id, RolePerk.role_id == role.id)
            )
            perk_entry = res.scalar_one_or_none()

            if not perk_entry:
                perk_entry = RolePerk(
                    guild_id=interaction.guild_id,
                    role_id=role.id,
                    role_name=role.name
                )
                session.add(perk_entry)

            if giveaway_access is not None:
                perk_entry.giveaway_access = giveaway_access
            if custom_color is not None:
                perk_entry.custom_color = custom_color

            await session.commit()

        await interaction.response.send_message(
            embed=success_embed(
                "Role Perks Updated",
                f"Perks for {role.mention}:\n"
                f"• Giveaway Access: `{'Enabled' if perk_entry.giveaway_access else 'Disabled'}`\n"
                f"• Custom Color: `{'Enabled' if perk_entry.custom_color else 'Disabled'}`"
            )
        )

    @roles_group.command(name="panel", description="Post an auto-refreshing live role roster panel")
    @app_commands.describe(
        category_name="Title for the panel",
        channel="Channel to post panel in (default current channel)"
    )
    @is_admin_or_has_role()
    async def roles_panel(
        self,
        interaction: discord.Interaction,
        category_name: str,
        channel: Optional[discord.TextChannel] = None
    ):
        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            return await interaction.response.send_message(
                embed=error_embed("Invalid Channel", "Must be a text channel."),
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        # Grab top 10 roles in guild
        roles = [r for r in interaction.guild.roles if not r.is_default() and not r.managed][-10:]
        role_ids = [r.id for r in reversed(roles)]

        async with AsyncSessionLocal() as session:
            panel = RolePanel(
                guild_id=interaction.guild_id,
                channel_id=target_channel.id,
                message_id=0,
                category=category_name,
                role_ids_json=json.dumps(role_ids),
                last_refreshed=datetime.utcnow()
            )
            session.add(panel)
            await session.commit()
            await session.refresh(panel)

            embed = await self._generate_panel_embed(interaction.guild, panel)
            msg = await target_channel.send(embed=embed)
            panel.message_id = msg.id
            await session.commit()

        await interaction.followup.send(
            embed=success_embed("Role Panel Created", f"Live panel posted in {target_channel.mention} (refreshes every 11 mins).")
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(RolesSystemCog(bot))
