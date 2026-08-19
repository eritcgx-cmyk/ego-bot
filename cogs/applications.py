"""
Applications and Staff Recruitment System Cog for Ego Bot
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from database.engine import AsyncSessionLocal
from database.models import ApplicationForm, ApplicationSubmission
from utils.permissions import is_admin_or_has_role, is_mod_or_has_role
from utils.embeds import ego_embed, success_embed, error_embed, info_embed
from utils.logger import log_action
from config import SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, logger

class DynamicApplicationModal(discord.ui.Modal):
    def __init__(self, form: ApplicationForm):
        super().__init__(title=f"Apply: {form.title[:40]}")
        self.form_id = form.id
        self.questions = form.questions[:5] # Max 5 for Discord modal items
        self.inputs = []

        for i, q in enumerate(self.questions):
            text_input = discord.ui.TextInput(
                label=f"Q{i+1}: {q[:40]}",
                placeholder=q[:100],
                style=discord.TextStyle.paragraph if len(q) > 40 else discord.TextStyle.short,
                required=True,
                max_length=1000
            )
            self.inputs.append(text_input)
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        answers = {self.questions[i]: self.inputs[i].value for i in range(len(self.inputs))}

        async with AsyncSessionLocal() as session:
            # Check cooldown
            res_form = await session.execute(select(ApplicationForm).where(ApplicationForm.id == self.form_id))
            form = res_form.scalar_one_or_none()

            if not form or not form.is_active:
                return await interaction.response.send_message("❌ This application form is no longer accepting submissions.", ephemeral=True)

            sub = ApplicationSubmission(
                guild_id=interaction.guild_id,
                form_id=form.id,
                user_id=interaction.user.id,
                answers_json=None,
                status="pending"
            )
            sub.answers = answers
            session.add(sub)
            await session.commit()
            await session.refresh(sub)

            # Route to review channel
            if form.review_channel_id:
                review_channel = interaction.guild.get_channel(form.review_channel_id)
                if review_channel and isinstance(review_channel, discord.TextChannel):
                    view = ApplicationReviewView(sub.id, form.id, interaction.user.id, form.role_on_accept_id)
                    embed = ego_embed(
                        title=f"📝 New Application: {form.title} (#{sub.id})",
                        description=f"**Applicant:** {interaction.user.mention} (`{interaction.user.id}`)\n**Submitted:** <t:{int(sub.submitted_at.timestamp())}:R>",
                        color=INFO_COLOR
                    )
                    for q, a in answers.items():
                        embed.add_field(name=f"❓ {q}", value=f"```\n{a}\n```", inline=False)
                    await review_channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            embed=success_embed(
                "Application Submitted",
                f"Your application for **{form.title}** has been received and routed to staff."
            ),
            ephemeral=True
        )

class ApplicationReviewView(discord.ui.View):
    def __init__(self, submission_id: int, form_id: int, applicant_id: int, role_on_accept_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.submission_id = submission_id
        self.form_id = form_id
        self.applicant_id = applicant_id
        self.role_on_accept_id = role_on_accept_id
        self.accept_btn.custom_id = f"app_accept:{submission_id}"
        self.deny_btn.custom_id = f"app_deny:{submission_id}"

    @discord.ui.button(label="Accept Application", style=discord.ButtonStyle.green, emoji="✅")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ You lack permissions to review applications.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(ApplicationSubmission).where(ApplicationSubmission.id == self.submission_id))
            sub = res.scalar_one_or_none()

            if not sub or sub.status != "pending":
                return await interaction.response.send_message("❌ This application is already resolved.", ephemeral=True)

            sub.status = "accepted"
            sub.reviewed_by = interaction.user.id
            await session.commit()

        # Grant reward role
        applicant = interaction.guild.get_member(self.applicant_id)
        role_str = ""
        if applicant and self.role_on_accept_id:
            role = interaction.guild.get_role(self.role_on_accept_id)
            if role:
                try:
                    await applicant.add_roles(role, reason=f"Application #{self.submission_id} accepted")
                    role_str = f" and assigned {role.mention}"
                except Exception:
                    pass

        self.disable_all_items()
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            embed=success_embed("Accepted", f"Application #{self.submission_id} was **Accepted** by {interaction.user.mention}{role_str}.")
        )

        if applicant:
            try:
                await applicant.send(f"🎉 Congratulations! Your application on **{interaction.guild.name}** was **Accepted**!")
            except Exception:
                pass

    @discord.ui.button(label="Deny Application", style=discord.ButtonStyle.red, emoji="✖️")
    async def deny_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ You lack permissions to review applications.", ephemeral=True)

        async with AsyncSessionLocal() as session:
            res = await session.execute(select(ApplicationSubmission).where(ApplicationSubmission.id == self.submission_id))
            sub = res.scalar_one_or_none()

            if not sub or sub.status != "pending":
                return await interaction.response.send_message("❌ This application is already resolved.", ephemeral=True)

            sub.status = "denied"
            sub.reviewed_by = interaction.user.id
            await session.commit()

        self.disable_all_items()
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            embed=error_embed("Denied", f"Application #{self.submission_id} was **Denied** by {interaction.user.mention}.")
        )

        applicant = interaction.guild.get_member(self.applicant_id)
        if applicant:
            try:
                await applicant.send(f"❌ Your application on **{interaction.guild.name}** was **Denied**.")
            except Exception:
                pass

class ApplicationsCog(commands.Cog, name="Applications"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    apps_group = app_commands.Group(name="applications", description="Custom application forms and recruitment")
    apps_admin_group = app_commands.Group(
        name="apps_admin",
        description="Staff administration controls for recruitment forms",
        default_permissions=discord.Permissions(manage_roles=True)
    )

    @apps_admin_group.command(name="setup", description="Create an application form with custom questions")
    @app_commands.describe(
        form_type="Type identifier (e.g. staff, mod, cc, partner)",
        title="Form Title",
        review_channel="Channel where submitted applications are sent for review",
        role_on_accept="Role automatically granted when accepted",
        cooldown_days="Cooldown days before denied applicants can re-apply",
        question1="First question",
        question2="Second question (optional)",
        question3="Third question (optional)",
        question4="Fourth question (optional)"
    )
    @is_admin_or_has_role()
    async def app_setup(
        self,
        interaction: discord.Interaction,
        form_type: str,
        title: str,
        review_channel: discord.TextChannel,
        role_on_accept: Optional[discord.Role] = None,
        cooldown_days: int = 7,
        question1: str = "Why do you want to join our team?",
        question2: Optional[str] = None,
        question3: Optional[str] = None,
        question4: Optional[str] = None
    ):
        questions = [question1]
        for q in [question2, question3, question4]:
            if q:
                questions.append(q)

        async with AsyncSessionLocal() as session:
            form = ApplicationForm(
                guild_id=interaction.guild_id,
                form_type=form_type.strip().lower(),
                title=title.strip(),
                review_channel_id=review_channel.id,
                role_on_accept_id=role_on_accept.id if role_on_accept else None,
                cooldown_days=cooldown_days,
                is_active=True
            )
            form.questions = questions
            session.add(form)
            await session.commit()
            await session.refresh(form)

        await interaction.response.send_message(
            embed=success_embed(
                "Application Form Created",
                f"**{title}** (Form ID: `{form.id}`)\n"
                f"• Type: `{form_type}`\n"
                f"• Review Channel: {review_channel.mention}\n"
                f"• Role on Accept: {role_on_accept.mention if role_on_accept else 'None'}\n"
                f"• Questions: `{len(questions)}`\n\n"
                f"Members can apply using `/applications apply form_id:{form.id}`."
            )
        )

    @apps_group.command(name="apply", description="Apply for an active application form")
    @app_commands.describe(form_id="ID of the application form")
    async def app_apply(self, interaction: discord.Interaction, form_id: int):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(ApplicationForm).where(
                    ApplicationForm.id == form_id,
                    ApplicationForm.guild_id == interaction.guild_id,
                    ApplicationForm.is_active == True
                )
            )
            form = res.scalar_one_or_none()

            if not form:
                return await interaction.response.send_message(
                    embed=error_embed("Form Not Found", "This application form does not exist or is closed."),
                    ephemeral=True
                )

            # Check denial cooldown
            res_sub = await session.execute(
                select(ApplicationSubmission)
                .where(
                    ApplicationSubmission.guild_id == interaction.guild_id,
                    ApplicationSubmission.form_id == form.id,
                    ApplicationSubmission.user_id == interaction.user.id,
                    ApplicationSubmission.status == "denied"
                )
                .order_by(ApplicationSubmission.submitted_at.desc())
            )
            last_denied = res_sub.scalar_one_or_none()

            if last_denied and form.cooldown_days:
                elapsed = datetime.utcnow() - last_denied.submitted_at
                cooldown_td = timedelta(days=form.cooldown_days)
                if elapsed < cooldown_td:
                    remaining = cooldown_td - elapsed
                    days_left = remaining.days
                    hours_left = int(remaining.seconds / 3600)
                    return await interaction.response.send_message(
                        embed=error_embed(
                            "Reapplication Cooldown",
                            f"You were previously denied for this position. Please wait **{days_left}d {hours_left}h** before reapplying."
                        ),
                        ephemeral=True
                    )

        modal = DynamicApplicationModal(form)
        await interaction.response.send_modal(modal)

    @apps_admin_group.command(name="list", description="List all pending applications")
    @is_mod_or_has_role()
    async def app_list(self, interaction: discord.Interaction):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(ApplicationSubmission)
                .where(
                    ApplicationSubmission.guild_id == interaction.guild_id,
                    ApplicationSubmission.status == "pending"
                )
                .order_by(ApplicationSubmission.submitted_at.desc())
            )
            pending = res.scalars().all()

        if not pending:
            return await interaction.response.send_message(
                embed=info_embed("Applications", "No pending applications at this time."),
                ephemeral=True
            )

        embed = ego_embed(title=f"📋 Pending Applications ({len(pending)})", color=INFO_COLOR)
        lines = []
        for s in pending[:15]:
            lines.append(f"• **Submission #{s.id}** (Form #{s.form_id}) by <@{s.user_id}> — <t:{int(s.submitted_at.timestamp())}:R>")

        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @apps_admin_group.command(name="close", description="Close an application form from accepting new submissions")
    @app_commands.describe(form_id="ID of the form to close")
    @is_admin_or_has_role()
    async def app_close(self, interaction: discord.Interaction, form_id: int):
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(ApplicationForm).where(ApplicationForm.id == form_id, ApplicationForm.guild_id == interaction.guild_id)
            )
            form = res.scalar_one_or_none()

            if not form:
                return await interaction.response.send_message(embed=error_embed("Not Found", f"Form #{form_id} does not exist."), ephemeral=True)

            form.is_active = False
            await session.commit()

        await interaction.response.send_message(embed=success_embed("Form Closed", f"Form **{form.title}** is now closed."))


async def setup(bot: commands.Bot):
    await bot.add_cog(ApplicationsCog(bot))
