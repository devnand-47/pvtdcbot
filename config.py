import os
from dotenv import load_dotenv

load_dotenv()

# ========= BOT TOKEN =========
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ========= IDs =========
# Add these IDs to your .env file
GUILD_ID = int(os.getenv("GUILD_ID", 1359708388644225045))

# Channels
RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID") or 0)
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID") or 0)
DEFAULT_ANNOUNCE_CHANNEL_ID = int(os.getenv("DEFAULT_ANNOUNCE_CHANNEL_ID") or 0)
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID") or 0)

# Roles considered staff/admin
ADMIN_ROLE_IDS = [
    int(os.getenv("ADMIN_ROLE_ID") or 0),
]

# ========= STORAGE =========
DB_PATH = "data/ultimatebot.db"
BACKUP_ROOT = "data/backups"
BACKUP_MESSAGES_PER_CHANNEL = 200

# ========= DASHBOARD AUTH =========
DASHBOARD_USERNAME = "admin"
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "DEV")
DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "super-secret-key-change-this")

# ========= DISCORD OAUTH2 =========
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/callback")

# ========= AUTO-MOD / RAID PROTECTION =========
VERIFICATION_CHANNEL_ID = int(os.getenv("VERIFICATION_CHANNEL_ID") or 0)
VERIFIED_ROLE_ID = int(os.getenv("VERIFIED_ROLE_ID") or 0)

RAID_JOIN_WINDOW = 30
RAID_JOIN_THRESHOLD = 5
LOCKDOWN_HARD_THRESHOLD = 15

FIREWALL_AUTO_RELEASE_MINUTES = -1  # set to -1 to disable auto-release
CAPTCHA_EXPIRE_SECONDS = 300
