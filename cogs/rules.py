"""
Rules Builder and Gatekeeper System Cog for Ego Bot.
Features:
- Persistent 'I Have Read and Agree to the Rules' verification button
- Fallback interaction listener for instant response on all rules messages
- Configurable rules list, auto-role assignment, and custom embeds
"""
from typing import Optional, List, Dict, Any
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import RulesConfig
from utils.permissions import is_admin_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import SUCCESS_COLOR, INFO_COLOR, logger

DEFAULT_RULES = [
    {"num": 1, "title": "Be Respectful", "desc": "Treat all members with kindness. Harassment, hate speech, and toxicity will result in immediate moderation."},
    {"num": 2, "title": "No Spam or Self-Promotion", "desc": "Keep all channels clean. Do not post unsolicited invite links, advertising, or mass mentions."},
    {"num": 3, "title": "Keep Channels on Topic", "desc": "Use designated channels for their intended subjects and follow channel-specific guidelines."},
    {"num": 4, "title": "Follow Discord Terms of Service", "desc": "Strictly abide by Discord's Terms of Service and Community Guidelines at all times."}
]

class RulesAgreeView(discord.ui.View):
    def __init__(self, guild_id: int = 0, agree_role_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.agree_role_id = agree_role_id
        self.agree_btn.custom_id = "rules_agree_btn"

    @discord.ui.button(label="I Have Read and Agree to the Rules", style=discord.ButtonStyle.green, emoji="✅", custom_id="rules_agree_btn")
    async def agree_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_rules_agreement(interaction, self.agree_role_id)


async def handle_rules_agreement(interaction: discord.Interaction, explicit_role_id: Optional[int] = None):
    """Unified handler for rules verification clicks."""
    guild = interaction.guild
    if not guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("❌ Must be inside a server.", ephemeral=True)

    role_id = explicit_role_id

    # 1. Check database for configured agree_role_id
    if not role_id:
        try:
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(RulesConfig).where(RulesConfig.guild_id == guild.id))
                cfg = res.scalar_one_or_none()
                if cfg and cfg.agree_role_id:
                    role_id = cfg.agree_role_id
        except Exception:
            pass

    # 2. Check master state file fallback
    if not role_id:
        try:
            from utils.state_manager import load_master_state
            state = load_master_state().get(str(guild.id), {})
            role_id = state.get("rules", {}).get("agree_role_id")
        except Exception:
            pass

    # 3. Fallback: Search server for common member/verified roles if unset
    role = None
    if role_id:
        role = guild.get_role(role_id)

    if not role:
        # Search for role named 'Member', 'Verified', or 'Access'
        for candidate_name in ["member", "members", "verified", "access", "unlocked"]:
            found = discord.utils.find(lambda r: r.name.lower() == candidate_name, guild.roles)
            if found:
                role = found
                break

    if not role:
        return await interaction.response.send_message(
            "✅ **You acknowledged the rules.** (No verification role is configured yet — staff can bind one with `/rules setup_role`).",
            ephemeral=True
        )

    if role in interaction.user.roles:
        return await interaction.response.send_message(
            f"✅ **You are already verified!** You already have the {role.mention} role.",
            ephemeral=True
        )

    try:
        await interaction.user.add_roles(role, reason="Agreed to server rules")
        await interaction.response.send_message(
            f"🎉 **Verification complete!** You have accepted the community rules and received {role.mention}.",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"⚠️ **Role Hierarchy Notice:** The bot cannot assign {role.mention} because Ego's role is positioned below it in **Server Settings > Roles**.\nPlease alert a server administrator.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to assign role: {e}", ephemeral=True)


class AddRuleModal(discord.ui.Modal, title="Add Server Rule"):
    def __init__(self, current_count: int):
        super().__init__()
        self.rule_num = current_count + 1

        self.title_input = discord.ui.TextInput(
            label=f"Rule #{self.rule_num} Title",
            placeholder="e.g. No NSFW Content",
            required=True,
            max_length=100
        )
        self.desc_input = discord.ui.TextInput(
            label="Rule Description",
            placeholder="Detailed explanation of the rule...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        )
        self.add_item(self.title_input)
        self.add_item(self.desc_input)

    async def on_submit(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(RulesConfig).where(RulesConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = RulesConfig(guild_id=interaction.guild_id, rules_json="[]")
                session.add(cfg)

            rules = list(cfg.rules)
            rules.append({
                "num": len(rules) + 1,
                "title": self.title_input.value.strip(),
                "desc": self.desc_input.value.strip()
            })
            cfg.rules = rules
            await session.commit()

        await interaction.response.send_message(
            embed=success_embed("Rule Added", f"Added Rule #{len(rules)}: **{self.title_input.value}**.\nUse `/rules republish` to update the rules channel."),
            ephemeral=True
        )


class RulesCog(commands.Cog, name="Rules"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Global fallback interaction listener for legacy and dynamic rules verification buttons."""
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "")
        if custom_id == "rules_agree_btn" or custom_id.startswith("rules_agree"):
            try:
                await handle_rules_agreement(interaction)
            except (discord.NotFound, discord.InteractionResponded):
                pass
            except Exception as e:
                logger.error(f"Error handling rules agreement interaction: {e}")

    def _build_rules_embed(self, guild: discord.Guild, rules: List[Dict[str, Any]]) -> discord.Embed:
        embed = ego_embed(
            title=f"📜 {guild.name} • Official Server Rules",
            description="Welcome! Please review our community rules. Failure to comply may lead to strikes, timeouts, kicks, or bans.\n",
            color=INFO_COLOR
        )
        for r in rules:
            embed.add_field(
                name=f"Rule {r.get('num', 1)}: {r.get('title', 'Rule')}",
                value=r.get("desc", ""),
                inline=False
            )
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        elif guild.splash:
            embed.set_image(url=guild.splash.url)

        embed.set_footer(text=f"{guild.name} • Click the button below to accept and verify")
        return embed

    rules_group = app_commands.Group(
        name="rules",
        description="Server rules builder and gatekeeper management",
        default_permissions=discord.Permissions(administrator=True)
    )

    @rules_group.command(name="setup_role", description="Bind the verification role granted when users agree to rules")
    @app_commands.describe(role="Role to grant upon accepting rules")
    @is_admin_or_has_role()
    async def rules_setup_role(self, interaction: discord.Interaction, role: discord.Role):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(RulesConfig).where(RulesConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = RulesConfig(guild_id=interaction.guild_id)
                session.add(cfg)

            cfg.agree_role_id = role.id
            await session.commit()

        try:
            from utils.state_manager import update_guild_state_section
            update_guild_state_section(interaction.guild_id, "rules", {"agree_role_id": role.id})
        except Exception:
            pass

        await interaction.response.send_message(
            embed=success_embed("Rules Role Configured", f"Members who click 'I Agree' will receive {role.mention}.")
        )

    @rules_group.command(name="publish", description="Post the official rules embed with agreement button")
    @app_commands.describe(channel="Channel to post rules in (defaults to current)", role="Role to give on agreement")
    @is_admin_or_has_role()
    async def rules_publish(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None, role: Optional[discord.Role] = None):
        target_ch = channel or interaction.channel
        guild = interaction.guild

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(RulesConfig).where(RulesConfig.guild_id == guild.id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = RulesConfig(guild_id=guild.id)
                cfg.rules = DEFAULT_RULES
                session.add(cfg)

            if role:
                cfg.agree_role_id = role.id

            rules = cfg.rules or DEFAULT_RULES
            embed = self._build_rules_embed(guild, rules)
            view = RulesAgreeView(guild_id=guild.id, agree_role_id=cfg.agree_role_id)

            msg = await target_ch.send(embed=embed, view=view)
            cfg.channel_id = target_ch.id
            cfg.message_id = msg.id
            cfg.enabled = True
            await session.commit()

        try:
            from utils.state_manager import update_guild_state_section
            update_guild_state_section(guild.id, "rules", {
                "channel_id": target_ch.id,
                "message_id": msg.id,
                "agree_role_id": cfg.agree_role_id,
                "enabled": True
            })
        except Exception:
            pass

        await interaction.response.send_message(
            embed=success_embed("Rules Published", f"Official rules posted in {target_ch.mention} with persistent agreement button."),
            ephemeral=True
        )

    @rules_group.command(name="add", description="Add a new rule to the server rules list")
    @is_admin_or_has_role()
    async def rules_add(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(RulesConfig).where(RulesConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()
            count = len(cfg.rules) if (cfg and cfg.rules) else len(DEFAULT_RULES)

        modal = AddRuleModal(current_count=count)
        await interaction.response.send_modal(modal)


async def setup(bot: commands.Bot):
    await bot.add_cog(RulesCog(bot))
