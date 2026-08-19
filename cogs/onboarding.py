"""
Native Discord Guild Onboarding API Integration Cog for Ego Bot
"""
from typing import Optional, List, Dict, Any
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from utils.permissions import is_guild_owner, is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import BOT_TOKEN, INFO_COLOR, logger

DISCORD_API_BASE = "https://discord.com/api/v10"

class OnboardingCog(commands.Cog, name="Onboarding"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _api_request(self, method: str, endpoint: str, json_data: Optional[dict] = None) -> Dict[str, Any]:
        """Make direct authorized HTTP requests to Discord Onboarding REST endpoints."""
        headers = {
            "Authorization": f"Bot {BOT_TOKEN}",
            "Content-Type": "application/json"
        }
        url = f"{DISCORD_API_BASE}{endpoint}"
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json=json_data) as resp:
                if resp.status == 204:
                    return {}
                data = await resp.json()
                if not resp.ok:
                    raise Exception(data.get("message", f"Discord API Error {resp.status}: {data}"))
                return data

    onboarding_group = app_commands.Group(
        name="onboarding",
        description="Configure native Discord Guild Onboarding",
        default_permissions=discord.Permissions(administrator=True)
    )

    @onboarding_group.command(name="preview", description="View current native Discord Onboarding configuration")
    @is_admin_or_has_role()
    async def onboarding_preview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            data = await self._api_request("GET", f"/guilds/{interaction.guild_id}/onboarding")
            enabled = data.get("enabled", False)
            default_channel_ids = data.get("default_channel_ids", [])
            prompts = data.get("prompts", [])
            mode = data.get("mode", 0)

            embed = ego_embed(
                title=f"🚀 Native Discord Onboarding: {interaction.guild.name}",
                description=f"Status: **{'Enabled' if enabled else 'Disabled'}** (Mode: `{mode}`)",
                color=INFO_COLOR
            )

            # Default channels
            ch_mentions = [f"<#{cid}>" for cid in default_channel_ids]
            embed.add_field(
                name=f"Default Channels ({len(default_channel_ids)})",
                value=", ".join(ch_mentions) if ch_mentions else "*None*",
                inline=False
            )

            # Prompts / Questions
            if prompts:
                for i, p in enumerate(prompts[:5], 1):
                    title = p.get("title", f"Prompt #{i}")
                    options = p.get("options", [])
                    opt_lines = []
                    for opt in options[:4]:
                        roles = [f"<@&{rid}>" for rid in opt.get("role_ids", [])]
                        opt_lines.append(f"• **{opt.get('title')}**: {' '.join(roles) if roles else 'No roles'}")
                    embed.add_field(name=f"❓ Prompt {i}: {title}", value="\n".join(opt_lines) if opt_lines else "*No options*", inline=False)
            else:
                embed.add_field(name="Onboarding Prompts", value="*No prompts configured.*", inline=False)

            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(embed=error_embed("Failed to Fetch Onboarding", str(e)))

    @onboarding_group.command(name="setup", description="Configure native onboarding default channels and prompts")
    @app_commands.describe(
        default_channel="Primary default channel for new members",
        prompt_title="Title of onboarding question (e.g. Choose Your Role)",
        option1_label="Label for choice 1",
        option1_role="Role awarded for choice 1",
        option2_label="Label for choice 2",
        option2_role="Role awarded for choice 2"
    )
    @is_guild_owner()
    async def onboarding_setup(
        self,
        interaction: discord.Interaction,
        default_channel: discord.TextChannel,
        prompt_title: str,
        option1_label: str,
        option1_role: discord.Role,
        option2_label: Optional[str] = None,
        option2_role: Optional[discord.Role] = None
    ):
        await interaction.response.defer(ephemeral=True)

        options_payload = [
            {
                "title": option1_label,
                "description": f"Grants the {option1_role.name} role",
                "role_ids": [str(option1_role.id)],
                "channel_ids": []
            }
        ]

        if option2_label and option2_role:
            options_payload.append({
                "title": option2_label,
                "description": f"Grants the {option2_role.name} role",
                "role_ids": [str(option2_role.id)],
                "channel_ids": []
            })

        payload = {
            "default_channel_ids": [str(default_channel.id)],
            "enabled": True,
            "mode": 0, # ONBOARDING_DEFAULT
            "prompts": [
                {
                    "title": prompt_title,
                    "options": options_payload,
                    "single_select": False,
                    "required": True,
                    "in_onboarding": True,
                    "type": 0 # MULTIPLE_CHOICE
                }
            ]
        }

        try:
            result = await self._api_request("PATCH", f"/guilds/{interaction.guild_id}/onboarding", json_data=payload)
            await interaction.followup.send(
                embed=success_embed(
                    "Native Onboarding Configured",
                    f"✅ Successfully configured native Discord Onboarding!\n\n"
                    f"• **Default Channel:** {default_channel.mention}\n"
                    f"• **Prompt:** {prompt_title}\n"
                    f"• **Options:** `{option1_label}` ({option1_role.mention})"
                    + (f", `{option2_label}` ({option2_role.mention})" if option2_label and option2_role else "")
                )
            )
            await log_action(
                interaction.guild,
                title="Discord Onboarding Configured",
                description=f"Prompt: {prompt_title} | Default Channel: {default_channel.mention}",
                moderator=interaction.user
            )
        except Exception as e:
            await interaction.followup.send(
                embed=error_embed("Failed to Configure Onboarding", f"API Error: {e}\n*Note: The Community feature must be enabled in Discord Server Settings for Onboarding to function.*")
            )

    @onboarding_group.command(name="toggle", description="Enable or disable native Discord Onboarding")
    @app_commands.describe(enabled="Enable (True) or Disable (False)")
    @is_guild_owner()
    async def onboarding_toggle(self, interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        try:
            payload = {"enabled": enabled}
            await self._api_request("PATCH", f"/guilds/{interaction.guild_id}/onboarding", json_data=payload)
            status_text = "Enabled" if enabled else "Disabled"
            await interaction.followup.send(embed=success_embed("Onboarding Updated", f"Native Discord Onboarding is now **{status_text}**."))
        except Exception as e:
            await interaction.followup.send(embed=error_embed("API Error", str(e)))

async def setup(bot: commands.Bot):
    await bot.add_cog(OnboardingCog(bot))
