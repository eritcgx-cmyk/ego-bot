"""
Ecco's Discord Utility - Bot Control, Dynamic Custom Status & Activity Manager
Interactive Command Prompt / CLI Console for Ego Discord Bot.
"""
import os
import sys
import json
import base64
import time
import urllib.request
import urllib.error
import ssl
from typing import Optional, List, Dict, Any

# Ensure parent directory is accessible
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from config import BOT_TOKEN, CLIENT_ID, logger

DISCORD_API_BASE = "https://discord.com/api/v10"
STATUS_FILE = os.path.join(os.path.dirname(__file__), "data", "saved_statuses.json")

class EccoDiscordUtility:
    def __init__(self, token: Optional[str] = None):
        self.token = token or BOT_TOKEN
        self.ctx = ssl.create_default_context()
        self.whitelist_file = os.path.join(os.path.dirname(__file__), "whitelist_config.json")
        self.whitelist = self._load_whitelist()
        self.statuses = self._load_statuses()

    def _load_whitelist(self) -> Dict[str, Any]:
        if os.path.exists(self.whitelist_file):
            try:
                with open(self.whitelist_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "whitelisted_guild_ids": [1539142640891732051],
            "whitelisted_owner_ids": [],
            "whitelisted_role_ids": [],
            "enforce_server_whitelist": False
        }

    def save_whitelist(self):
        with open(self.whitelist_file, "w", encoding="utf-8") as f:
            json.dump(self.whitelist, f, indent=2)
        print("💾 Whitelist saved.")

    def _load_statuses(self) -> List[Dict[str, Any]]:
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return [
            {"id": 1, "type": "playing", "text": "Roblox", "details": "Grinding Blox Fruits with friends", "url": None, "author": "Ecco"},
            {"id": 2, "type": "playing", "text": "Grand Theft Auto VI", "details": "Exploring Vice City", "url": None, "author": "Ecco"},
            {"id": 3, "type": "watching", "text": "you keep /egoing me", "details": None, "url": None, "author": "Ecco"}
        ]

    def save_statuses(self):
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.statuses, f, indent=2)
        print("💾 Custom statuses saved.")

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

    def change_bot_avatar(self, image_path: str) -> bool:
        try:
            if os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
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

    def send_channel_message(self, channel_id: str, message: str) -> bool:
        payload = {"content": message}
        res = self._api_request("POST", f"/channels/{channel_id}/messages", payload)
        if res:
            print(f"✅ Message sent to channel {channel_id} (Message ID: {res.get('id')})")
            return True
        return False

    def print_menu(self):
        os.system("cls" if os.name == "nt" else "clear")
        user = self.get_current_bot_user()
        bot_tag = f"{user.get('username')}#{user.get('discriminator', '0')}" if user else "Offline"
        bot_id = user.get("id", "Unknown") if user else "N/A"
        guilds = self.get_bot_guilds()
        self.statuses = self._load_statuses()

        print("=" * 70)
        print("  👑 ECCO'S DISCORD UTILITY • EGO BOT CONTROL CONSOLE")
        print("=" * 70)
        print(f"  🤖 Bot Name: {bot_tag} (ID: {bot_id})")
        print(f"  🏰 Connected Guilds ({len(guilds)}):")
        for g in guilds:
            print(f"     • {g.get('name')} (`{g.get('id')}`)")
        print(f"  💾 Saved Custom Statuses in Library: {len(self.statuses)}")
        print("=" * 70)
        print("  [1] 🎮 Type & Save Custom Status / Activity (e.g. Playing Roblox)")
        print("  [2] 📋 View & Apply from Saved Status Library")
        print("  [3] 💬 Send Quick Chat Message into Server Channel")
        print("  [4] 👤 Bot Profile & Avatar Manager")
        print("  [5] 🛡️ Server & Role Whitelist Configuration")
        print("  [0] ❌ Exit")
        print("=" * 70)

    def run_cli(self):
        while True:
            self.print_menu()
            choice = input("Select an option (0-5): ").strip()

            if choice == "1":
                self._menu_add_custom_status()
            elif choice == "2":
                self._menu_view_saved_statuses()
            elif choice == "3":
                self._menu_send_chat()
            elif choice == "4":
                self._menu_profile()
            elif choice == "5":
                self._menu_whitelist()
            elif choice == "0":
                print("Exiting Ecco's Discord Utility.")
                break
            else:
                input("Invalid option. Press Enter to continue...")

    def _menu_add_custom_status(self):
        print("\n--- 🎮 TYPE & AUTO-SAVE CUSTOM STATUS ---")
        print("Select Type:")
        print("  1. Playing (Game, e.g. Roblox, Minecraft, GTA VI)")
        print("  2. Streaming (Twitch / YouTube live stream)")
        print("  3. Watching (Anime, Movie, Server)")
        print("  4. Listening (Spotify, Podcast)")
        print("  5. Custom Status (Profile text)")

        t_choice = input("Type (1-5): ").strip()
        type_map = {"1": "playing", "2": "streaming", "3": "watching", "4": "listening", "5": "custom"}
        stype = type_map.get(t_choice, "playing")

        text = input("Enter Status Text or Game Name: ").strip()
        if not text:
            input("Text cannot be empty. Press Enter...")
            return

        details = input("Enter In-Game Details / State (optional): ").strip()
        url = None
        if stype == "streaming":
            url = input("Enter Stream URL (e.g. https://twitch.tv/...): ").strip() or "https://twitch.tv/discord"

        next_id = max([s["id"] for s in self.statuses], default=0) + 1
        entry = {
            "id": next_id,
            "type": stype,
            "text": text,
            "details": details if details else None,
            "url": url,
            "author": "Local CLI"
        }
        self.statuses.append(entry)
        self.save_statuses()

        print(f"\n✅ Created & Saved Status #{next_id}: [{stype.title()}] {text} ({details or ''})")
        print("• It is now in your saved list and will be included in the 1-minute rotation cycle!")
        input("\nPress Enter to continue...")

    def _menu_view_saved_statuses(self):
        self.statuses = self._load_statuses()
        print(f"\n--- 📋 SAVED CUSTOM STATUSES LIBRARY ({len(self.statuses)}) ---")
        for s in self.statuses:
            emoji = "🎮" if s["type"] == "playing" else "📺" if s["type"] == "streaming" else "👀" if s["type"] == "watching" else "🎧" if s["type"] == "listening" else "✨"
            desc = f"• Details: {s.get('details')}" if s.get("details") else ""
            print(f"  [{s['id']:02d}] {emoji} [{s['type'].title()}] {s['text']} {desc}")

        print("\nOptions:")
        print("  • Type an ID number to delete that status")
        print("  • Type 'b' to go back")
        action = input("Selection: ").strip()

        if action.isdigit():
            target_id = int(action)
            self.statuses = [s for s in self.statuses if s["id"] != target_id]
            self.save_statuses()
            print(f"✅ Removed Status #{target_id}.")

        input("\nPress Enter to continue...")

    def _menu_send_chat(self):
        print("\n--- 💬 SEND CHAT MESSAGE AS BOT ---")
        guilds = self.get_bot_guilds()
        if not guilds:
            input("Bot is not in any server yet. Press Enter...")
            return

        g = guilds[0]
        channels = self._api_request("GET", f"/guilds/{g['id']}/channels")
        text_channels = [c for c in channels if c.get("type") == 0]

        print(f"Channels in {g['name']}:")
        for i, c in enumerate(text_channels, 1):
            print(f"  {i}. #{c['name']} (ID: {c['id']})")

        c_choice = input(f"Select channel (1-{len(text_channels)}): ").strip()
        if c_choice.isdigit() and 1 <= int(c_choice) <= len(text_channels):
            target_ch = text_channels[int(c_choice) - 1]
            msg = input(f"Enter message for #{target_ch['name']}: ").strip()
            if msg:
                self.send_channel_message(str(target_ch["id"]), msg)
        input("\nPress Enter to continue...")

    def _menu_profile(self):
        print("\n--- 👤 BOT PROFILE & AVATAR CONTROL ---")
        print("1. Change Bot Username")
        print("2. Change Bot Avatar (Local Image File)")
        print("3. Back")
        sub = input("Select (1-3): ").strip()

        if sub == "1":
            new_name = input("Enter new name: ").strip()
            if new_name:
                self.change_bot_username(new_name)
        elif sub == "2":
            path = input("Enter image path (.png/.jpg): ").strip().strip('"')
            if path:
                self.change_bot_avatar(path)
        input("\nPress Enter to continue...")

    def _menu_whitelist(self):
        print("\n--- 🛡️ SERVER & ROLE WHITELIST MANAGER ---")
        print(f"1. Toggle Enforce Whitelist (Current: {'ON' if self.whitelist.get('enforce_server_whitelist') else 'OFF'})")
        print("2. Add Server ID to Whitelist")
        print("3. View Whitelist JSON")
        print("4. Back")

        sub = input("Select (1-4): ").strip()
        if sub == "1":
            curr = self.whitelist.get("enforce_server_whitelist", False)
            self.whitelist["enforce_server_whitelist"] = not curr
            self.save_whitelist()
        elif sub == "2":
            sid = input("Enter Server ID: ").strip()
            if sid.isdigit():
                self.whitelist.setdefault("whitelisted_guild_ids", []).append(int(sid))
                self.save_whitelist()
        elif sub == "3":
            print(json.dumps(self.whitelist, indent=2))
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    app = EccoDiscordUtility()
    app.run_cli()
