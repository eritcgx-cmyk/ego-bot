"""
Database Models for all Ego bot systems.
"""
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Boolean,
    Integer,
    Text,
    DateTime,
    ForeignKey
)
from database.engine import Base

class GuildConfig(Base):
    __tablename__ = "guild_configs"

    guild_id = Column(BigInteger, primary_key=True, index=True)
    mod_log_channel_id = Column(BigInteger, nullable=True)
    admin_role_id = Column(BigInteger, nullable=True)
    mod_role_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Giveaway(Base):
    __tablename__ = "giveaways"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, unique=True, index=True, nullable=False)
    prize = Column(String(255), nullable=False)
    host_id = Column(BigInteger, nullable=False)
    end_time = Column(DateTime, nullable=False, index=True)
    winners_count = Column(Integer, default=1, nullable=False)
    required_role_id = Column(BigInteger, nullable=True)
    status = Column(String(32), default="active", index=True) # active, ended, cancelled
    participants_json = Column(Text, default="[]") # List of user IDs
    winners_json = Column(Text, default="[]") # List of winner user IDs

    @property
    def participants(self) -> List[int]:
        return json.loads(self.participants_json or "[]")

    @participants.setter
    def participants(self, value: List[int]):
        self.participants_json = json.dumps(value)

    @property
    def winners(self) -> List[int]:
        return json.loads(self.winners_json or "[]")

    @winners.setter
    def winners(self, value: List[int]):
        self.winners_json = json.dumps(value)

class WelcomeConfig(Base):
    __tablename__ = "welcome_configs"

    guild_id = Column(BigInteger, primary_key=True, index=True)
    enabled = Column(Boolean, default=False)
    channel_id = Column(BigInteger, nullable=True)
    title = Column(String(255), default="Welcome to {server}!")
    message = Column(Text, default="Hey {user}, welcome! You are member #{membercount}.")
    embed_color = Column(Integer, default=0x5865F2)
    dm_enabled = Column(Boolean, default=False)
    dm_message = Column(Text, default="Welcome to {server}! Make sure to read the rules.")

class AutomodConfig(Base):
    __tablename__ = "automod_configs"

    guild_id = Column(BigInteger, primary_key=True, index=True)
    enabled = Column(Boolean, default=False)
    spam_threshold = Column(Integer, default=5) # Messages within 5 seconds
    mass_mention_limit = Column(Integer, default=5)
    block_invites = Column(Boolean, default=True)
    banned_words_json = Column(Text, default="[]")
    warn_threshold = Column(Integer, default=2)
    timeout_threshold = Column(Integer, default=4) # In minutes or infraction points
    kick_threshold = Column(Integer, default=6)
    ban_threshold = Column(Integer, default=8)

    @property
    def banned_words(self) -> List[str]:
        return json.loads(self.banned_words_json or "[]")

    @banned_words.setter
    def banned_words(self, value: List[str]):
        self.banned_words_json = json.dumps(value)

class AutomodInfraction(Base):
    __tablename__ = "automod_infractions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    action_type = Column(String(64), nullable=False) # warn, timeout, kick, ban
    reason = Column(String(512), nullable=False)
    points = Column(Integer, default=1)
    timestamp = Column(DateTime, default=datetime.utcnow)

class FriendGroupConfig(Base):
    __tablename__ = "friend_group_configs"

    guild_id = Column(BigInteger, primary_key=True, index=True)
    enabled = Column(Boolean, default=False)
    max_fgs_per_user = Column(Integer, default=1)
    max_fgs_per_guild = Column(Integer, default=50)
    min_members = Column(Integer, default=4)

class FriendGroup(Base):
    __tablename__ = "friend_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    creator_id = Column(BigInteger, nullable=False)
    category_id = Column(BigInteger, nullable=True)
    text_channel_id = Column(BigInteger, nullable=True)
    voice_channel_id = Column(BigInteger, nullable=True)
    status = Column(String(32), default="pending", index=True) # pending, active, disbanded
    members_json = Column(Text, default="[]") # List of user IDs accepted
    invited_json = Column(Text, default="[]") # List of user IDs pending

    @property
    def members(self) -> List[int]:
        return json.loads(self.members_json or "[]")

    @members.setter
    def members(self, value: List[int]):
        self.members_json = json.dumps(value)

    @property
    def invited(self) -> List[int]:
        return json.loads(self.invited_json or "[]")

    @invited.setter
    def invited(self, value: List[int]):
        self.invited_json = json.dumps(value)

class RolePerk(Base):
    __tablename__ = "role_perks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    role_id = Column(BigInteger, unique=True, index=True, nullable=False)
    role_name = Column(String(100), nullable=False)
    giveaway_access = Column(Boolean, default=False)
    custom_color = Column(Boolean, default=False)
    perks_json = Column(Text, default="{}")

    @property
    def perks(self) -> Dict[str, Any]:
        return json.loads(self.perks_json or "{}")

    @perks.setter
    def perks(self, value: Dict[str, Any]):
        self.perks_json = json.dumps(value)

class RolePanel(Base):
    __tablename__ = "role_panels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, unique=True, nullable=False)
    category = Column(String(64), default="All")
    role_ids_json = Column(Text, default="[]")
    last_refreshed = Column(DateTime, default=datetime.utcnow)

    @property
    def role_ids(self) -> List[int]:
        return json.loads(self.role_ids_json or "[]")

    @role_ids.setter
    def role_ids(self, value: List[int]):
        self.role_ids_json = json.dumps(value)

class ContentCreatorTier(Base):
    __tablename__ = "cc_tiers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    tier_name = Column(String(64), nullable=False) # tier1, tier2, tier3, star, famous
    role_id = Column(BigInteger, nullable=True)
    required_followers = Column(Integer, default=1000)
    required_views = Column(Integer, default=5000)

class ContentCreatorSubmission(Base):
    __tablename__ = "cc_submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    platform = Column(String(64), nullable=False)
    username = Column(String(100), nullable=False)
    followers = Column(Integer, default=0)
    views = Column(Integer, default=0)
    proof_url = Column(String(512), nullable=True)
    status = Column(String(32), default="pending") # pending, approved, denied
    timestamp = Column(DateTime, default=datetime.utcnow)

class InviteTier(Base):
    __tablename__ = "invite_tiers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    tier_number = Column(Integer, nullable=False) # 1 through 10
    threshold = Column(Integer, nullable=False)
    role_id = Column(BigInteger, nullable=True)

class UserInviteStat(Base):
    __tablename__ = "user_invite_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    regular = Column(Integer, default=0)
    left = Column(Integer, default=0)
    fake = Column(Integer, default=0)
    bonus = Column(Integer, default=0)

    @property
    def total(self) -> int:
        return max(0, (self.regular + self.bonus) - (self.left + self.fake))

class IdentityVerifyConfig(Base):
    __tablename__ = "identity_verify_configs"

    guild_id = Column(BigInteger, primary_key=True, index=True)
    enabled = Column(Boolean, default=False)
    channel_id = Column(BigInteger, nullable=True)
    message_id = Column(BigInteger, nullable=True)
    min_account_age_days = Column(Integer, default=7)
    review_channel_id = Column(BigInteger, nullable=True)
    roles_json = Column(Text, default="{}") # { "He/Him": role_id, "She/Her": role_id, ... }

    @property
    def roles_map(self) -> Dict[str, int]:
        return json.loads(self.roles_json or "{}")

    @roles_map.setter
    def roles_map(self, value: Dict[str, int]):
        self.roles_json = json.dumps(value)

class RulesConfig(Base):
    __tablename__ = "rules_configs"

    guild_id = Column(BigInteger, primary_key=True, index=True)
    channel_id = Column(BigInteger, nullable=True)
    message_id = Column(BigInteger, nullable=True)
    agree_role_id = Column(BigInteger, nullable=True)
    rules_json = Column(Text, default="[]") # List of { "num": 1, "title": "...", "desc": "..." }
    enabled = Column(Boolean, default=False)

    @property
    def rules(self) -> List[Dict[str, Any]]:
        return json.loads(self.rules_json or "[]")

    @rules.setter
    def rules(self, value: List[Dict[str, Any]]):
        self.rules_json = json.dumps(value)

class ApplicationForm(Base):
    __tablename__ = "application_forms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    form_type = Column(String(64), nullable=False) # staff, cc, partnership, custom
    title = Column(String(128), nullable=False)
    description = Column(String(512), nullable=True)
    review_channel_id = Column(BigInteger, nullable=True)
    role_on_accept_id = Column(BigInteger, nullable=True)
    cooldown_days = Column(Integer, default=7)
    is_active = Column(Boolean, default=True)
    questions_json = Column(Text, default="[]") # List of question strings (max 5 for Discord modal)

    @property
    def questions(self) -> List[str]:
        return json.loads(self.questions_json or "[]")

    @questions.setter
    def questions(self, value: List[str]):
        self.questions_json = json.dumps(value)

class ApplicationSubmission(Base):
    __tablename__ = "application_submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, index=True, nullable=False)
    form_id = Column(Integer, ForeignKey("application_forms.id"), nullable=False)
    user_id = Column(BigInteger, index=True, nullable=False)
    answers_json = Column(Text, default="{}") # { "Q1": "A1", ... }
    status = Column(String(32), default="pending") # pending, accepted, denied
    submitted_at = Column(DateTime, default=datetime.utcnow)
    reviewed_by = Column(BigInteger, nullable=True)
    review_note = Column(String(512), nullable=True)

    @property
    def answers(self) -> Dict[str, str]:
        return json.loads(self.answers_json or "{}")

    @answers.setter
    def answers(self, value: Dict[str, str]):
        self.answers_json = json.dumps(value)
