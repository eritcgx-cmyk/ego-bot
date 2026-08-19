# Ego Discord Bot — Production Multi-System Engine

A production-grade, modular Discord bot named **"Ego"** built using `discord.py 2.4+`, `SQLAlchemy 2.0` (async engine supporting PostgreSQL and SQLite), full slash commands architecture, persistent views, and native Discord REST API integrations.

---

## 📋 Features & Systems Overview

| # | System | Key Slash Commands | Description |
|---|---|---|---|
| **1** | **Giveaways** | `/giveaway start`, `/giveaway end`, `/giveaway reroll`, `/gwannounce` | Persistent interactive entry buttons, automatic winner draw on expiry, role requirements, restarts resilience. |
| **2** | **Welcome Messages** | `/welcome setup`, `/welcome preview`, `/welcome toggle` | Custom embed templates with `{user}`, `{mention}`, `{server}`, `{membercount}` placeholders and optional DMs. |
| **3** | **Automod & Escalation** | `/automod status`, `/automod toggle`, `/automod set_thresholds`, `/automod add_word` | Token-bucket spam detection, invite link block, mass mentions filter, word blacklist, and escalation ladder (Warn $\rightarrow$ Timeout $\rightarrow$ Kick $\rightarrow$ Ban). |
| **4** | **Friend Groups (FG)** | `/fg config`, `/fg start`, `/fg invite`, `/fg rename`, `/fg kick`, `/fg disband` | Multi-step FG lifecycle. Creator invites 4+ members with Accept/Deny buttons; upon acceptance, auto-provisions private category + text + voice channels. |
| **5** | **Role System** | `/roles import_presets`, `/roles create_custom`, `/roles perks`, `/roles panel` | Catalog of 1,200+ categorized role presets (Content Creator, Verified, Mod, Rich/Status, Custom), live auto-refreshing roster panel (11m task), and DB perk flags. |
| **6** | **Content Creator Verification** | `/cc verify`, `/cc config_tier`, `/cc tiers` | Stat submission modal for TikTok/YouTube/Twitch/Kick, admin threshold tiers, review channel card with Accept/Deny buttons and auto-role grant. |
| **7** | **Invite Tracking & Levels** | `/invites mystats`, `/invites leaderboard`, `/invites config_tier`, `/invites panel` | Real-time invite cache tracking join sources, top inviters leaderboard, and 10 configurable rank reward tiers. |
| **8** | **Identity & Gender Verification** | `/verify_panel setup` | Non-photo identity/gender selection button panel, anti-troll account age gate check, and staff manual review escalation. |
| **9** | **General & Utilities** | `/announce`, `/say`, `/purge`, `/poll`, `/remind`, `/embed builder`, `/ping`, `/uptime`, `/botinfo`, `/serverinfo`, `/userinfo`, `/avatar`, `/help` | Mod utilities, interactive modal embed builder, timed polls, async DM reminders, and categorized help manual. |
| **10** | **Rules Builder & Gate** | `/rules setup`, `/rules edit`, `/rules addrule`, `/rules removerule`, `/rules republish` | Interactive wizard, auto-generated `#rules` channel, numbered rules embed, and persistent "I Agree" gate for member verification. |
| **11** | **Native Discord Onboarding** | `/onboarding setup`, `/onboarding edit`, `/onboarding preview`, `/onboarding toggle` | Interfaces directly with Discord's native Guild Onboarding REST API (`PATCH /guilds/{id}/onboarding`) for default channels and onboarding prompt questions. |
| **12** | **Applications System** | `/applications setup`, `/applications apply`, `/applications list`, `/applications close` | Custom application form builder, dynamic modal questionnaires, review channel routing with Accept/Deny decisions, and reapplication cooldowns. |

---

## 🛠️ Step 1: Discord Developer Portal Setup

1. **Create Application**:
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications).
   - Click **New Application** $\rightarrow$ Name it `Ego` $\rightarrow$ Click **Create**.

2. **Create Bot User & Get Token**:
   - Go to the **Bot** tab on the left sidebar.
   - Click **Reset Token** (or **Add Bot** if prompted).
   - Copy the token and save it safely (this will be your `BOT_TOKEN`).

3. **Enable Privileged Gateway Intents** (CRITICAL):
   - In the **Bot** tab, scroll down to **Privileged Gateway Intents**.
   - Enable all three toggles:
     - ✅ **Presence Intent**
     - ✅ **Server Members Intent**
     - ✅ **Message Content Intent**
   - Click **Save Changes**.

4. **Generate Bot Invite URL**:
   - Go to **OAuth2** $\rightarrow$ **URL Generator**.
   - Under **Scopes**, check:
     - `bot`
     - `applications.commands`
   - Under **Bot Permissions**, check:
     - `Administrator` (recommended for full channel provisioning & role management) or grant specific permissions (`Manage Roles`, `Manage Channels`, `Kick Members`, `Ban Members`, `Send Messages`, `Manage Messages`, `Embed Links`, `Attach Files`, `Read Message History`, `Connect`, `Speak`).
   - Copy the generated URL and open it in your browser to invite Ego to your Discord server.

---

## ☁️ Step 2: Deploying to Render (Cloud Hosting)

Render provides persistent **Background Workers** and **Managed PostgreSQL** databases.

### Method A: One-Click Render Blueprint (Recommended)
1. Push this repository to your GitHub account.
2. In the [Render Dashboard](https://dashboard.render.com), click **New +** $\rightarrow$ **Blueprint**.
3. Connect your GitHub repository. Render will automatically parse [`render.yaml`](render.yaml) and configure:
   - Worker Service: `ego-discord-bot`
   - Database: `ego-postgres-db` (PostgreSQL)
4. Under the `BOT_TOKEN` environment variable prompt, paste your bot token.
5. Click **Apply** to deploy.

### Method B: Manual Render Worker Setup
1. Create a **PostgreSQL** database on Render:
   - Click **New +** $\rightarrow$ **PostgreSQL**.
   - Name: `ego-postgres-db`.
   - Copy the **Internal Database URL**.
2. Create a **Background Worker**:
   - Click **New +** $\rightarrow$ **Background Worker**.
   - Connect your repo.
   - Runtime: `Python 3`.
   - Build Command: `pip install -r requirements.txt`.
   - Start Command: `python bot.py`.
3. Add Environment Variables in Render:
   - `BOT_TOKEN`: Your Discord Bot Token.
   - `DATABASE_URL`: Your Render PostgreSQL Connection String (starts with `postgresql+asyncpg://` or `postgres://`).
   - `LOG_LEVEL`: `INFO`.
4. Click **Create Background Worker**.

---

## 💻 Step 3: Local Development (SQLite)

1. **Clone and create virtual environment**:
   ```bash
   git clone <repo-url>
   cd ego-bot
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure `.env`**:
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   ```env
   BOT_TOKEN=your_actual_token_here
   DATABASE_URL=sqlite+aiosqlite:///ego_bot.db
   ```

4. **Start the bot**:
   ```bash
   python bot.py
   ```

---

## ⚙️ Initial Server Configuration

Once the bot joins your server, configure your logging channel and administrative roles using the `/config` slash commands:

1. `/config modlog channel:#mod-logs` — Sets the server audit log destination.
2. `/config roles admin_role:@Admin mod_role:@Moderator` — Sets administrative and moderation roles.
3. `/config status` — Verifies current server settings.

---

## 📁 Repository Structure

```
ego-bot/
├── bot.py                     # Main bot lifecycle, cog loader, slash synchronization
├── config.py                  # Environment config and styling
├── requirements.txt           # Python dependencies
├── Procfile                   # Process file for cloud container
├── render.yaml                # Render Blueprint file
├── .env.example               # Environment variables template
├── database/
│   ├── engine.py              # Async SQLAlchemy engine (asyncpg / aiosqlite)
│   └── models.py              # ORM models for all 12 subsystems
├── cogs/
│   ├── giveaways.py           # 1. Giveaways
│   ├── welcome.py             # 2. Welcome & DMs
│   ├── automod.py             # 3. Automod & Escalation
│   ├── friend_groups.py       # 4. Friend Groups (FG)
│   ├── roles_system.py        # 5. Role Presets & 11m Panels
│   ├── content_creator.py     # 6. CC Verification & Tiers
│   ├── invites.py             # 7. Invite Tracking & Rewards
│   ├── identity_verify.py     # 8. Identity/Gender Non-photo Verification
│   ├── general.py             # 9. General, Announce & Embed Builder
│   ├── rules.py               # 10. Rules Builder & Gate
│   ├── onboarding.py          # 11. Discord Native Onboarding REST API
│   └── applications.py        # 12. Custom Applications & Review
├── data/
│   └── role_presets.json      # 1,200 curated role preset templates
├── scripts/
│   └── generate_roles.py      # Role preset generator utility
└── utils/
    ├── permissions.py         # Permission checks & decorators
    ├── embeds.py              # Standard styled embed generators
    ├── logger.py              # Mod-log audit dispatcher
    └── views.py               # Reusable confirmation & paginator views
```
