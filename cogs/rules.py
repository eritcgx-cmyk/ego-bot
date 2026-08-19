"""
Rules Builder and Gatekeeper System Cog for Ego Bot
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
    def __init__(self, guild_id: int, agree_role_id: Optional[int]):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.agree_role_id = agree_role_id
        self.agree_btn.custom_id = f"rules_agree:{guild_id}"

    @discord.ui.button(label="I Have Read and Agree to the Rules", style=discord.ButtonStyle.green, emoji="✅")
    async def agree_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.agree_role_id:
            return await interaction.response.send_message("✅ You acknowledged the rules.", ephemeral=True)

        role = interaction.guild.get_role(self.agree_role_id)
        if not role:
            return await interaction.response.send_message("❌ Verification role not found.", ephemeral=True)

        member = interaction.user
        if isinstance(member, discord.Member):
            if role in member.roles:
                return await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
            try:
                await member.add_roles(role, reason="Agreed to server rules")
                await interaction.response.send_message(f"🎉 Verification complete! You have received {role.mention}.", ephemeral=True)
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

    async def restore_rules_views(self):
        """Restore persistent views for rules verification."""
        try:
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(RulesConfig).where(RulesConfig.enabled == True))
                configs = res.scalars().all()

                for cfg in configs:
                    if cfg.message_id:
                        view = RulesAgreeView(cfg.guild_id, cfg.agree_role_id)
                        self.bot.add_view(view, message_id=cfg.message_id)
        except Exception as e:
            logger.warning(f"Could not restore rules views: {e}")

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
        embed.set_footer(text="Click the button below to accept the rules and unlock channels.")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return embed

    rules_group = app_commands.Group(name="rules", description="Server rules configuration, wizard, and agreement gate")

    @rules_group.command(name="setup", description="Deploy the server rules into a dedicated channel")
    @app_commands.describe(
        channel="Channel to post rules in (will create #rules if empty)",
        agree_role="Role to grant when user clicks 'I Agree'",
        use_default_rules="Pre-populate with standard production server rules"
    )
    @is_admin_or_has_role()
    async def rules_setup(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        agree_role: Optional[discord.Role] = None,
        use_default_rules: bool = True
    ):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        target_channel = channel
        if not target_channel:
            # Check if #rules exists
            existing = discord.utils.get(guild.text_channels, name="rules")
            if existing:
                target_channel = existing
            else:
                try:
                    target_channel = await guild.create_text_channel(
                        name="rules",
                        topic="Official server guidelines and member verification",
                        reason="Rules system deployment"
                    )
                except Exception as e:
                    return await interaction.followup.send(embed=error_embed("Failed to Create Channel", f"Error: {e}"))

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(RulesConfig).where(RulesConfig.guild_id == guild.id))
            cfg = res.scalar_one_or_none()

            if not cfg:
                cfg = RulesConfig(guild_id=guild.id)
                session.add(cfg)

            rules = cfg.rules if (cfg.rules and not use_default_rules) else DEFAULT_RULES
            cfg.rules = rules
            cfg.channel_id = target_channel.id
            cfg.agree_role_id = agree_role.id if agree_role else None
            cfg.enabled = True

            embed = self._build_rules_embed(guild, rules)
            view = RulesAgreeView(guild.id, cfg.agree_role_id)
            msg = await target_channel.send(embed=embed, view=view)
            cfg.message_id = msg.id
            await session.commit()

            self.bot.add_view(view, message_id=msg.id)

        await interaction.followup.send(
            embed=success_embed(
                "Rules Deployed",
                f"Rules have been published in {target_channel.mention}!\n"
                f"Agreement Gate Role: {agree_role.mention if agree_role else 'None'}"
            )
        )

    @rules_group.command(name="addrule", description="Add a new numbered rule via modal")
    @is_admin_or_has_role()
    async def rules_addrule(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(RulesConfig).where(RulesConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()
            count = len(cfg.rules) if cfg else 0

        modal = AddRuleModal(count)
        await interaction.response.send_modal(modal)

    @rules_group.command(name="removerule", description="Remove a rule by number")
    @app_commands.describe(rule_number="Number of the rule to delete")
    @is_admin_or_has_role()
    async def rules_removerule(self, interaction: discord.Interaction, rule_number: int):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(RulesConfig).where(RulesConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg or not cfg.rules:
                return await interaction.response.send_message(embed=error_embed("No Rules", "No rules configured."), ephemeral=True)

            rules = list(cfg.rules)
            if not (1 <= rule_number <= len(rules)):
                return await interaction.response.send_message(embed=error_embed("Invalid Number", f"Rule #{rule_number} does not exist."), ephemeral=True)

            removed = rules.pop(rule_number - 1)
            # Renumber
            for i, r in enumerate(rules, 1):
                r["num"] = i

            cfg.rules = rules
            await session.commit()

        await interaction.response.send_message(
            embed=success_embed("Rule Removed", f"Removed Rule #{rule_number} ({removed.get('title')}). Run `/rules republish` to update the message.")
        )

    @rules_group.command(name="republish", description="Republish or refresh the rules embed in the rules channel")
    @is_admin_or_has_role()
    async def rules_republish(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(RulesConfig).where(RulesConfig.guild_id == interaction.guild_id))
            cfg = res.scalar_one_or_none()

            if not cfg or not cfg.channel_id:
                return await interaction.response.send_message(embed=error_embed("Not Found", "Rules channel not configured. Run `/rules setup`."), ephemeral=True)

            channel = interaction.guild.get_channel(cfg.channel_id)
            if not channel or not isinstance(channel, discord.TextChannel):
                return await interaction.response.send_message(embed=error_embed("Channel Unavailable", "Configured rules channel was not found."), ephemeral=True)

            embed = self._build_rules_embed(interaction.guild, cfg.rules)
            view = RulesAgreeView(interaction.guild.id, cfg.agree_role_id)

            if cfg.message_id:
                try:
                    msg = await channel.fetch_message(cfg.message_id)
                    await msg.edit(embed=embed, view=view)
                    return await interaction.response.send_message(embed=success_embed("Rules Updated", f"Updated message in {channel.mention}."))
                except Exception:
                    pass

            # Post new
            new_msg = await channel.send(embed=embed, view=view)
            cfg.message_id = new_msg.id
            await session.commit()
            self.bot.add_view(view, message_id=new_msg.id)

        await interaction.response.send_message(embed=success_embed("Rules Published", f"Published in {channel.mention}."))

async def setup(bot: commands.Bot):
    cog = RulesCog(bot)
    await bot.add_cog(cog)
    await cog.restore_rules_views()
