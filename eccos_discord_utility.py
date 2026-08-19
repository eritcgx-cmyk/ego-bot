"""
Ecco's Discord Utility - Bot Control, Status Rotator & Whitelist Manager
Interactive Local Control Console for Ego Discord Bot.
"""
import os
import sys
import json
import base64
import asyncio
import urllib.request
import urllib.error
import ssl
from typing import Optional, List, Dict, Any

# Ensure parent directory is accessible
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from config import BOT_TOKEN, CLIENT_ID, logger

DISCORD_API_BASE = "https://discord.com/api/v10"

# 100+ Categorized Status Presets for Local Management
STATUS_CATALOG = {
    "📢 Advertisement Presets": [
        "👑 Join our VIP Hub • /help",
        "🎉 Active Giveaways • /giveaway",
        "💎 Unlock Custom Roles • /roles perks",
        "📈 Invite Leaderboards • /invites",
        "🚀 Verified Creator Ranks • /cc verify",
        "👥 Friend Groups • /fg start",
        "📜 Read Server Rules • /rules",
        "📝 Staff Applications Open • /applications",
        "🛡️ Protected by Ego Automod",
        "✨ Claim Your Roles in #verification",
        "🔥 Elite Nitro Booster Perks",
        "⚡ discord.gg/ecco • Join Now",
        "🎁 Massive Server Drops Today",
        "📢 Check #announcements for updates",
        "🌟 Level Up Your Invites for Perks",
        "💬 Active Voice & Text Channels",
        "🏆 Host Your Own Private Friend Group",
        "🎬 Content Creator Spotlight",
        "🤖 Powered by Ego Production Engine",
        "💎 Diamond & Obsidian VIP Status Tiers",
        "🎵 24/7 Music, Gaming & Hangouts",
        "🛡️ Zero-Tolerance Automod Defense",
        "📊 Real-Time Server Growth Analytics",
        "🎯 Daily Community Challenges",
        "🚀 Explore 1,200+ Custom Role Presets"
    ],
    "💬 Community & Scale Presets": [
        "Chatting with {membercount} members",
        "Protecting {guildcount} servers",
        "with {membercount} verified users",
        "over {guildcount} active realms",
        "Ego v2.0 • Serving {membercount} users",
        "the member count grow ({membercount})",
        "to community voice channels",
        "in {guildcount} partner hubs",
        "welcoming new members daily",
        "24/7 High-Performance Uptime",
        "friend groups collaborate live",
        "moderation logs & security filters",
        "managing {membercount} profiles",
        "to staff tickets & reviews",
        "leaderboard rankings shift live",
        "supporting top creator communities",
        "live role roster panels refresh",
        "to verification requests",
        "active across {guildcount} servers",
        "giveaways countdown to draw",
        "Ego Central Management Engine",
        "server analytics & audit logs",
        "community engagement soar",
        "exclusive perk holders",
        "high-speed Discord interactions"
    ],
    "⚡ Aesthetic & Flex Presets": [
        "⚡ Sovereign Authority",
        "💎 The Obsidian Syndicate",
        "🌙 Midnight Chroma Drift",
        "🔮 Ethereal Resonance",
        "🪐 Cosmic Horizon Phase",
        "👑 Apex Status Achieved",
        "✨ Neon Glitch Matrix",
        "🏆 Monarch Dynasty",
        "💠 Diamond Tier VIP",
        "🛡️ Sentinel Security Shield",
        "🌌 Astral Pulse Frequency",
        "⚡ High Voltage Infrastructure",
        "🔥 Infernal Sovereign",
        "❄️ Frost Radiant Aura",
        "🌀 Cyberpunk Synthwave Vibe",
        "⚜️ Imperial Council",
        "💎 Whale Status Lounge",
        "🎯 Zero Tolerance Automod",
        "🖤 Monochrome Aesthetic",
        "🌟 Star Creator Spotlight",
        "🚀 Quantum Execution Layer",
        "👑 Legendary Rank Prestige",
        "🔱 Celestial Authority",
        "💠 Platinum Standard",
        "⚡ Ego • Production Supreme"
    ],
    "🎮 Gaming & Entertainment Presets": [
        "🔴 Live Stream Highlights",
        "Valorant • Ranked Competitive",
        "Minecraft • Community SMP",
        "Roblox • Studio Developer",
        "Twitch Partner Streams",
        "YouTube Viral Highlights",
        "TikTok Trending Clips",
        "Grand Theft Auto VI",
        "League of Legends • Challenger",
        "Esports Championship Finals",
        "Overwatch 2 • Grandmaster",
        "Anime & Movie Night",
        "Counter-Strike 2 • Premier",
        "Speedrun World Records",
        "Fortnite • Champion Division",
        "Podcasts & Interviews",
        "Apex Legends • Predator Tier",
        "Community Clip Showcase",
        "Call of Duty • Warzone",
        "Kick Streamers Live",
        "Cyberpunk 2077 • Phantom Liberty",
        "Creator Highlights in #clips",
        "Rocket League • Supersonic Legend",
        "Music Festival Stream",
        "Ego Arcade • Winner Takes All"
    ]
}

class EccoDiscordUtility:
    def __init__(self, token: Optional[str] = None):
        self.token = token or BOT_TOKEN
        self.ctx = ssl.create_default_context()
        self.whitelist_file = os.path.join(os.path.dirname(__file__), "whitelist_config.json")
        self.whitelist = self._load_whitelist()

    def _load_whitelist(self) -> Dict[str, Any]:
        if os.path.exists(self.whitelist_file):
            try:
                with open(self.whitelist_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "whitelisted_guild_ids": [],
            "whitelisted_owner_ids": [],
            "whitelisted_role_ids": [],
            "enforce_server_whitelist": False
        }

    def save_whitelist(self):
        with open(self.whitelist_file, "w", encoding="utf-8") as f:
            json.dump(self.whitelist, f, indent=2)
        print("💾 Whitelist configuration saved.")

    def _api_request(self, method: str, endpoint: str, data: Optional[dict] = None) -> Any:
        headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (EgoEngine, 2.0)"
        }
        url = f"{DISCORD_API_BASE}{endpoint}"
        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=self.ctx) as resp:
                if resp.status == 204:
                    return {}
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8")
            print(f"❌ Discord API Error ({e.code}): {err}")
            return None

    def get_current_bot_user(self) -> Optional[Dict[str, Any]]:
        return self._api_request("GET", "/users/@me")

    def get_bot_guilds(self) -> List[Dict[str, Any]]:
        guilds = self._api_request("GET", "/users/@me/guilds")
        return guilds if isinstance(guilds, list) else []

    def change_bot_username(self, new_name: str) -> bool:
        res = self._api_request("PATCH", "/users/@me", {"username": new_name.strip()})
        if res:
            print(f"✅ Bot username updated to: {res.get('username')}")
            return True
        return False

    def change_bot_avatar(self, image_path_or_url: str) -> bool:
        try:
            if os.path.exists(image_path_or_url):
                with open(image_path_or_url, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                mime = "image/png" if image_path_or_url.lower().endswith(".png") else "image/jpeg"
                avatar_data = f"data:{mime};base64,{b64}"
                res = self._api_request("PATCH", "/users/@me", {"avatar": avatar_data})
                if res:
                    print("✅ Bot avatar updated successfully.")
                    return True
            else:
                print("❌ Local image file not found.")
        except Exception as e:
            print(f"❌ Failed to set avatar: {e}")
        return False

    def print_menu(self):
        os.system("cls" if os.name == "nt" else "clear")
        user = self.get_current_bot_user()
        bot_tag = f"{user.get('username')}#{user.get('discriminator', '0')}" if user else "Offline / Invalid Token"
        bot_id = user.get("id", "Unknown") if user else "N/A"
        guilds = self.get_bot_guilds()

        print("=" * 65)
        print("  👑 ECCO'S DISCORD UTILITY • EGO BOT CONTROL CONSOLE")
        print("=" * 65)
        print(f"  🤖 Bot: {bot_tag} (ID: {bot_id})")
        print(f"  🏰 Connected Servers: {len(guilds)}")
        print(f"  🔒 Whitelist Enforcement: {'ENABLED' if self.whitelist.get('enforce_server_whitelist') else 'DISABLED'}")
        print("=" * 65)
        print("  [1] 🎮 Bot Profile Control (Username, Avatar, Connection)")
        print("  [2] 🔄 Status Rotator Utility (100+ Presets & Custom)")
        print("  [3] 🛡️ Server & Role Whitelist Manager")
        print("  [4] 🔐 Command Access Layer & Permissions Audit")
        print("  [5] 🚀 Live Cloud Hosting & Render Status")
        print("  [0] ❌ Exit")
        print("=" * 65)

    def run_cli(self):
        while True:
            self.print_menu()
            choice = input("Select an option (0-5): ").strip()

            if choice == "1":
                self._menu_bot_control()
            elif choice == "2":
                self._menu_status_rotator()
            elif choice == "3":
                self._menu_whitelist()
            elif choice == "4":
                self._menu_command_access()
            elif choice == "5":
                self._menu_render_status()
            elif choice == "0":
                print("Exiting Ecco's Discord Utility.")
                break
            else:
                input("Invalid option. Press Enter to continue...")

    def _menu_bot_control(self):
        print("\n--- 🎮 BOT PROFILE & IDENTITY CONTROL ---")
        print("1. Change Bot Username")
        print("2. Change Bot Avatar (from file path)")
        print("3. List Connected Servers")
        print("4. Back to Main Menu")
        sub = input("Select (1-4): ").strip()

        if sub == "1":
            new_name = input("Enter new bot username: ").strip()
            if new_name:
                self.change_bot_username(new_name)
        elif sub == "2":
            img = input("Enter local path to image (.png/.jpg): ").strip().strip('"')
            if img:
                self.change_bot_avatar(img)
        elif sub == "3":
            guilds = self.get_bot_guilds()
            print(f"\n🏰 Connected Servers ({len(guilds)}):")
            for g in guilds:
                print(f"  • {g.get('name')} (ID: {g.get('id')})")
        input("\nPress Enter to continue...")

    def _menu_status_rotator(self):
        print("\n--- 🔄 DISCORD STATUS ROTATOR UTILITY (100+ PRESETS) ---")
        print("Categories:")
        categories = list(STATUS_CATALOG.keys())
        for i, cat in enumerate(categories, 1):
            print(f"  {i}. {cat} ({len(STATUS_CATALOG[cat])} presets)")
        print("  5. View All 100+ Presets")
        print("  6. Trigger Immediate Status Rotation")
        print("  7. Back")

        sub = input("Select: ").strip()
        if sub in ["1", "2", "3", "4"]:
            cat = categories[int(sub) - 1]
            print(f"\n--- {cat} ---")
            for j, preset in enumerate(STATUS_CATALOG[cat], 1):
                print(f"  [{j:02d}] {preset}")
        elif sub == "5":
            for cat, presets in STATUS_CATALOG.items():
                print(f"\n=== {cat} ===")
                for j, preset in enumerate(presets, 1):
                    print(f"  • {preset}")
        input("\nPress Enter to continue...")

    def _menu_whitelist(self):
        print("\n--- 🛡️ SERVER & ROLE WHITELIST MANAGER ---")
        print(f"1. Toggle Enforce Whitelist (Current: {'ON' if self.whitelist.get('enforce_server_whitelist') else 'OFF'})")
        print("2. Add Server ID to Whitelist")
        print("3. Remove Server ID from Whitelist")
        print("4. Add Owner / Admin User ID")
        print("5. Add Whitelisted Role ID")
        print("6. View Whitelist Configuration")
        print("7. Back")

        sub = input("Select: ").strip()
        if sub == "1":
            curr = self.whitelist.get("enforce_server_whitelist", False)
            self.whitelist["enforce_server_whitelist"] = not curr
            self.save_whitelist()
        elif sub == "2":
            sid = input("Enter Server ID to whitelist: ").strip()
            if sid.isdigit():
                self.whitelist.setdefault("whitelisted_guild_ids", []).append(int(sid))
                self.save_whitelist()
        elif sub == "3":
            sid = input("Enter Server ID to remove: ").strip()
            if sid.isdigit() and int(sid) in self.whitelist.get("whitelisted_guild_ids", []):
                self.whitelist["whitelisted_guild_ids"].remove(int(sid))
                self.save_whitelist()
        elif sub == "4":
            uid = input("Enter Owner/Admin User ID: ").strip()
            if uid.isdigit():
                self.whitelist.setdefault("whitelisted_owner_ids", []).append(int(uid))
                self.save_whitelist()
        elif sub == "5":
            rid = input("Enter Whitelisted Role ID: ").strip()
            if rid.isdigit():
                self.whitelist.setdefault("whitelisted_role_ids", []).append(int(rid))
                self.save_whitelist()
        elif sub == "6":
            print("\n📋 Current Whitelist JSON:")
            print(json.dumps(self.whitelist, indent=2))
        input("\nPress Enter to continue...")

    def _menu_command_access(self):
        print("\n--- 🔐 COMMAND ACCESS LAYER & PERMISSION AUDIT ---")
        print("Public Commands (Open to all regular members):")
        print("  • /help, /poll, /avatar, /userinfo, /serverinfo, /ping, /uptime, /botinfo")
        print("  • /invites mystats, /invites leaderboard, /invites panel")
        print("  • /cc verify, /cc tiers")
        print("  • /fg start, /fg invite, /fg rename, /fg kick, /fg disband")
        print("  • /applications apply")
        print("\nAdministrative Commands (Protected by Owner / Whitelisted Roles):")
        print("  • /config modlog, /config roles, /config status")
        print("  • /roles import_presets, /roles create_custom, /roles perks, /roles panel")
        print("  • /rules setup, /rules addrule, /rules removerule, /rules republish")
        print("  • /onboarding setup, /onboarding toggle")
        print("  • /automod set_thresholds, /automod toggle, /automod add_word")
        print("  • /purge, /say, /announce, /gwannounce, /giveaway start, /giveaway end")
        input("\nPress Enter to continue...")

    def _menu_render_status(self):
        print("\n--- 🚀 RENDER CLOUD HOSTING STATUS ---")
        RENDER_KEY = "rnd_B2nlGG2PEoBu10loc7IrMgS0bk6i"
        headers = {
            "Authorization": f"Bearer {RENDER_KEY}",
            "Accept": "application/json"
        }
        url = "https://api.render.com/v1/services/srv-da2u4r61egvs739ugm4g"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, context=self.ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(f"Service Name: {data.get('name')}")
                print(f"Service ID:   {data.get('id')}")
                print(f"Status:       {data.get('suspended')}")
                print(f"Dashboard:    {data.get('dashboardUrl')}")
                print(f"Live URL:     {data.get('serviceDetails', {}).get('url')}")
        except Exception as e:
            print(f"Could not reach Render API: {e}")
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    app = EccoDiscordUtility()
    app.run_cli()
