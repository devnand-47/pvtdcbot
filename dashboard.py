# dashboard.py

import asyncio
from pathlib import Path
from time import localtime, strftime
import json
import logging
import urllib.parse

import aiosqlite
import httpx
from fastapi import FastAPI, Form, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature

from config import (
    DB_PATH,
    GUILD_ID,
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    DISCORD_REDIRECT_URI,
    DASHBOARD_SECRET_KEY,
)

# Set up logging for dashboard
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("Dashboard")

app = FastAPI(title="UltimateBot Dashboard")
templates = Jinja2Templates(directory="templates")

DB_FILE = Path(DB_PATH)
serializer = URLSafeTimedSerializer(DASHBOARD_SECRET_KEY)
SESSION_COOKIE_NAME = "ub_session_v2"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


# ---------- DB helpers ----------
async def get_db():
    conn = await aiosqlite.connect(DB_FILE)
    conn.row_factory = aiosqlite.Row
    return conn


# ---------- Auth helpers ----------
def get_logged_in_user(request: Request):
    """Returns the user dictionary from the session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    try:
        user_data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return user_data
    except BadSignature:
        return None

def require_login(request: Request):
    user = get_logged_in_user(request)
    if not user:
        return None
    return user

async def get_guild_stats(guild_id: int):
    """Return stats for graphs: labels (dates) + series per action for a specific guild."""
    if not DB_FILE.exists():
        return {"labels": [], "series": []}

    conn = await get_db()
    cur = await conn.execute(
        """
        SELECT
          date(datetime(created_at, 'unixepoch')) AS d,
          action,
          COUNT(*) as c
        FROM moderation_logs
        WHERE guild_id = ?
        GROUP BY d, action
        ORDER BY d ASC
        """,
        (guild_id,),
    )
    rows = await cur.fetchall()
    await conn.close()

    if not rows:
        return {"labels": [], "series": []}

    dates = sorted({r["d"] for r in rows})
    actions = sorted({r["action"] for r in rows})

    date_index = {d: i for i, d in enumerate(dates)}
    data_map = {action: [0] * len(dates) for action in actions}

    for r in rows:
        d = r["d"]
        a = r["action"]
        c = r["c"]
        idx = date_index[d]
        data_map[a][idx] = c

    series = []
    for action, counts in data_map.items():
        series.append(
            {
                "name": action,
                "type": "line",
                "smooth": True,
                "data": counts,
            }
        )

    return {"labels": dates, "series": series}

async def get_logs_data(guild_id: int, limit: int) -> list:
    if not DB_FILE.exists():
        return []

    conn = await get_db()
    cur = await conn.execute(
        """
        SELECT user_id, actor_id, action, reason, created_at
        FROM moderation_logs
        WHERE guild_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (guild_id, limit),
    )
    rows = await cur.fetchall()
    await conn.close()

    logs = []
    for r in rows:
        ts_str = strftime("%Y-%m-%d %H:%M:%S", localtime(r["created_at"]))
        logs.append({
            "timestamp": ts_str,
            "action": r["action"],
            "target": r["user_id"] or "-",
            "actor": r["actor_id"] or "-",
            "reason": r["reason"] or "-"
        })
    return logs

async def get_bot_guild_data(guild_id: int):
    """Fetches live channels and roles from the bot's internal IPC server."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"http://127.0.0.1:8001/api/guild/{guild_id}")
            if res.status_code == 200:
                return res.json()
    except Exception as e:
        log.warning(f"Failed to fetch bot IPC data for guild {guild_id}: {e}")
    return {"channels": [], "roles": [], "member_count": 0}

# ---------- Routes: Discord OAuth2 ----------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: bool = False):
    user = get_logged_in_user(request)
    if user:
        return RedirectResponse("/servers", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.get("/login/discord")
async def login_discord():
    """Redirects the user to the Discord OAuth2 authorization page."""
    if not DISCORD_CLIENT_ID:
        return HTMLResponse("Discord Client ID is missing in .env", status_code=500)
    
    auth_params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds"
    }
    url = f"https://discord.com/api/oauth2/authorize?{urllib.parse.urlencode(auth_params)}"
    return RedirectResponse(url)

@app.get("/callback")
async def discord_callback(request: Request, code: str = None, error: str = None):
    """Handles the OAuth2 callback from Discord."""
    if error or not code:
        return RedirectResponse("/login?error=true", status_code=303)

    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient() as client:
        # 1. Exchange code for token
        try:
            token_res = await client.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
            if token_res.status_code != 200:
                log.error(f"Failed to get token! Status: {token_res.status_code}. Response: {token_res.text}")
                return RedirectResponse("/login?error=true", status_code=303)
                
            token_data = token_res.json()
            access_token = token_data.get("access_token")
            if not access_token:
                log.error(f"Discord API returned no access token: {token_data}")
                return RedirectResponse("/login?error=true", status_code=303)
                
            auth_headers = {"Authorization": f"Bearer {access_token}"}
        except Exception as e:
            log.error(f"Failed token exhange network request: {e}")
            return RedirectResponse("/login?error=true", status_code=303)

        # 2. Fetch user profile
        try:
            user_res = await client.get("https://discord.com/api/users/@me", headers=auth_headers)
            if user_res.status_code != 200:
                log.error(f"Failed to fetch user profile: {user_res.text}")
                return RedirectResponse("/login?error=true", status_code=303)
            user_profile = user_res.json()
            
            user_id = user_profile.get("id")
            if not user_id:
                log.error(f"Discord API returned no User ID: {user_profile}")
                return RedirectResponse("/login?error=true", status_code=303)

            avatar_id = user_profile.get("avatar")
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_id}.png" if avatar_id else None
        except Exception as e:
            log.error(f"Error parsing Discord OAuth User data: {e}")
            return RedirectResponse("/login?error=true", status_code=303)

        # 3. Fetch user guilds
        guilds_res = await client.get("https://discord.com/api/users/@me/guilds", headers=auth_headers)
        if guilds_res.status_code != 200:
            return RedirectResponse("/login?error=true", status_code=303)
        
        raw_guilds = guilds_res.json()
        
        # 4. Filter guilds where user has MANAGE_GUILD (0x20) or ADMINISTRATOR (0x8)
        manageable_guilds = []
        for g in raw_guilds:
            perms = int(g.get("permissions", 0))
            if (perms & 0x8) == 0x8 or (perms & 0x20) == 0x20:
                manageable_guilds.append({
                    "id": g["id"],
                    "name": g["name"],
                    "icon": g.get("icon", None)
                })

        # 5. Create session
        session_data = {
            "id": user_profile["id"],
            "username": user_profile.get("global_name") or user_profile["username"],
            "avatar_url": avatar_url,
            "guilds": manageable_guilds
        }

        token = serializer.dumps(session_data)
        resp = RedirectResponse("/servers", status_code=303)
        resp.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return resp

@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE_NAME)
    return resp


# ---------- Landing Page ----------
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    user = get_logged_in_user(request)
    return templates.TemplateResponse("landing.html", {"request": request, "user": user})

# ---------- Server Selector ----------
@app.get("/servers", response_class=HTMLResponse)
async def server_selector(request: Request):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse("servers.html", {
        "request": request,
        "user": user,
        "guilds": user.get("guilds", [])
    })


# ---------- Specific Server Dashboard Routes ----------
def get_guild_from_session(user_data, guild_id: str):
    """Validates the user has access to this guild and returns the guild obj."""
    if not user_data:
        return None
    for g in user_data.get("guilds", []):
        if str(g["id"]) == str(guild_id):
            return g
    return None


@app.get("/dashboard/{guild_id}/home", response_class=HTMLResponse)
async def dashboard_home(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return HTMLResponse("Unauthorized or Server not found.", status_code=403)

    target_guild_id = int(guild_id)
    stats = await get_guild_stats(target_guild_id)
    stats_json = json.dumps(stats)
    logs_data = await get_logs_data(target_guild_id, 20)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": user,
        "guild": guild,
        "stats_json": stats_json,
        "logs_data": logs_data
    })


@app.get("/dashboard/{guild_id}/welcome", response_class=HTMLResponse)
async def dashboard_welcome(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return HTMLResponse("Unauthorized", status_code=403)

    target_guild_id = int(guild_id)
    bot_data = await get_bot_guild_data(target_guild_id)
    
    conn = await get_db()
    
    try:
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN welcome_card_enabled INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN welcome_card_theme TEXT DEFAULT 'default'")
    except Exception:
        pass

    cur = await conn.execute(
        """
        SELECT welcome_channel_id, welcome_message, welcome_title, welcome_color, welcome_image_url, autorole_id, welcome_card_enabled, welcome_card_theme
        FROM guild_settings WHERE guild_id = ?
        """,
        (target_guild_id,),
    )
    row = await cur.fetchone()
    await conn.close()

    return templates.TemplateResponse("welcome.html", {
        "request": request,
        "user": user,
        "guild": guild,
        "bot_data": bot_data,
        "welcome_channel_id": row["welcome_channel_id"] if row and row["welcome_channel_id"] else "",
        "welcome_message": row["welcome_message"] if row and row["welcome_message"] else "{mention}, welcome to {server}.",
        "welcome_title": row["welcome_title"] if row and row["welcome_title"] else "🚨 New Operative Connected",
        "welcome_color": row["welcome_color"] if row and row["welcome_color"] else "#E74C3C",
        "welcome_image_url": row["welcome_image_url"] if row and row["welcome_image_url"] else "",
        "autorole_id": row["autorole_id"] if row and row["autorole_id"] else "",
        "welcome_card_enabled": row["welcome_card_enabled"] if row and row["welcome_card_enabled"] else 0,
        "welcome_card_theme": row["welcome_card_theme"] if row and "welcome_card_theme" in row.keys() and row["welcome_card_theme"] else 'default',
    })

@app.get("/dashboard/{guild_id}/broadcast", response_class=HTMLResponse)
async def dashboard_broadcast_page(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return HTMLResponse("Unauthorized", status_code=403)

    target_guild_id = int(guild_id)
    bot_data = await get_bot_guild_data(target_guild_id)
    
    conn = await get_db()
    cur = await conn.execute("SELECT default_announce_id, updates_channel_id FROM guild_settings WHERE guild_id = ?", (target_guild_id,))
    row = await cur.fetchone()
    await conn.close()

    default_announce_id = row["default_announce_id"] if row and row["default_announce_id"] else ""
    updates_channel_id = row["updates_channel_id"] if row and row["updates_channel_id"] else ""

    return templates.TemplateResponse("broadcast.html", {
        "request": request,
        "user": user,
        "guild": guild,
        "bot_data": bot_data,
        "default_announce_id": default_announce_id,
        "updates_channel_id": updates_channel_id
    })


@app.get("/dashboard/{guild_id}/automod", response_class=HTMLResponse)
async def dashboard_automod_page(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    guild = get_guild_from_session(user, guild_id)
    if not guild:
         return HTMLResponse("Unauthorized", status_code=403)

    target_guild_id = int(guild_id)
    bot_data = await get_bot_guild_data(target_guild_id)

    conn = await get_db()
    # Ensure columns exist before querying
    for col_query in [
        "ALTER TABLE guild_settings ADD COLUMN automod_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_settings ADD COLUMN firewall_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_settings ADD COLUMN spam_protection_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_settings ADD COLUMN bad_words TEXT DEFAULT ''",
        "ALTER TABLE guild_settings ADD COLUMN afk_move_enabled INTEGER DEFAULT 0"
    ]:
        try:
            await conn.execute(col_query)
        except Exception:
            pass

    cur = await conn.execute(
        """
        SELECT automod_enabled, firewall_enabled, spam_protection_enabled, bad_words, afk_move_enabled
        FROM guild_settings WHERE guild_id = ?
        """,
        (target_guild_id,),
    )
    row = await cur.fetchone()
    await conn.close()
    
    # If no row yet, use defaults
    data = {
        "automod_enabled": 0,
        "firewall_enabled": 0,
        "spam_protection_enabled": 0,
        "bad_words": "",
        "afk_move_enabled": 0
    }
    if row:
        data["automod_enabled"] = row["automod_enabled"] or 0
        data["firewall_enabled"] = row["firewall_enabled"] or 0
        data["spam_protection_enabled"] = row["spam_protection_enabled"] or 0
        data["bad_words"] = row["bad_words"] or ""
        data["afk_move_enabled"] = row["afk_move_enabled"] or 0

    return templates.TemplateResponse("automod.html", {
        "request": request,
        "user": user,
        "guild": guild,
        "bot_data": bot_data,
        "data": data
    })

@app.get("/dashboard/{guild_id}/logs", response_class=HTMLResponse)
async def dashboard_logs_page(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    guild = get_guild_from_session(user, guild_id)
    if not guild:
         return HTMLResponse("Unauthorized", status_code=403)

    target_guild_id = int(guild_id)
    
    conn = await get_db()
    try:
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN voice_log_channel_id INTEGER")
    except Exception:
        pass
        
    cur = await conn.execute("SELECT voice_log_channel_id FROM guild_settings WHERE guild_id = ?", (target_guild_id,))
    row = await cur.fetchone()
    await conn.close()
    
    voice_log_channel_id = str(row["voice_log_channel_id"]) if row and row["voice_log_channel_id"] else ""
    
    logs_data = await get_logs_data(target_guild_id, 100) # Fetch up to 100 logs
    bot_data = await get_bot_guild_data(target_guild_id)

    return templates.TemplateResponse("logs.html", {
        "request": request,
        "user": user,
        "guild": guild,
        "logs_data": logs_data,
        "bot_data": bot_data,
        "voice_log_channel_id": voice_log_channel_id,
        "active_page": "logs"
    })

@app.post("/dashboard/{guild_id}/settings/logs")
async def save_logs(
    request: Request,
    guild_id: str,
    voice_log_channel_id: str = Form(""),
):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    conn = await get_db()
    
    try:
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN voice_log_channel_id INTEGER")
    except Exception:
        pass

    await conn.execute(
        """
        INSERT INTO guild_settings (guild_id, voice_log_channel_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            voice_log_channel_id = excluded.voice_log_channel_id
        """,
        (
            target_guild_id,
            int(voice_log_channel_id) if voice_log_channel_id else None,
        ),
    )
    await conn.commit()
    await conn.close()
    
    return RedirectResponse(f"/dashboard/{guild_id}/logs?success=1", status_code=303)


# ---------- POST Settings Routes ----------
@app.post("/dashboard/{guild_id}/settings/welcome")
async def save_welcome(
    request: Request,
    guild_id: str,
    welcome_channel_id: str = Form(""),
    welcome_message: str = Form(""),
    welcome_title: str = Form(""),
    welcome_color: str = Form(""),
    welcome_image_url: str = Form(""),
    autorole_id: str = Form(""),
    welcome_card_enabled: str = Form("0"),
    welcome_card_theme: str = Form("default"),
):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    conn = await get_db()
    
    for col_query in [
        "ALTER TABLE guild_settings ADD COLUMN welcome_title TEXT DEFAULT '🚨 New Operative Connected'",
        "ALTER TABLE guild_settings ADD COLUMN welcome_color TEXT DEFAULT '#E74C3C'",
        "ALTER TABLE guild_settings ADD COLUMN welcome_image_url TEXT",
        "ALTER TABLE guild_settings ADD COLUMN welcome_card_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_settings ADD COLUMN welcome_card_theme TEXT DEFAULT 'default'",
    ]:
        try:
            await conn.execute(col_query)
        except Exception: 
            pass

    await conn.execute(
        """
        INSERT INTO guild_settings (guild_id, welcome_channel_id, welcome_message, welcome_title, welcome_color, welcome_image_url, autorole_id, welcome_card_enabled, welcome_card_theme)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            welcome_channel_id = excluded.welcome_channel_id,
            welcome_message    = excluded.welcome_message,
            welcome_title      = excluded.welcome_title,
            welcome_color      = excluded.welcome_color,
            welcome_image_url  = excluded.welcome_image_url,
            autorole_id        = excluded.autorole_id,
            welcome_card_enabled = excluded.welcome_card_enabled,
            welcome_card_theme = excluded.welcome_card_theme
        """,
        (
            target_guild_id,
            int(welcome_channel_id) if welcome_channel_id else None,
            welcome_message,
            welcome_title,
            welcome_color,
            welcome_image_url,
            int(autorole_id) if autorole_id else None,
            int(welcome_card_enabled),
            welcome_card_theme,
        ),
    )
    await conn.commit()
    await conn.close()
    return RedirectResponse(f"/dashboard/{guild_id}/welcome?success=1", status_code=303)


@app.post("/dashboard/{guild_id}/settings/automod")
async def save_automod(
    request: Request,
    guild_id: str,
    automod_enabled: str = Form("0"),
    firewall_enabled: str = Form("0"),
    spam_protection_enabled: str = Form("0"),
    bad_words: str = Form(""),
    afk_move_enabled: str = Form("0"),
):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    conn = await get_db()
    
    for col_query in [
        "ALTER TABLE guild_settings ADD COLUMN automod_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_settings ADD COLUMN firewall_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_settings ADD COLUMN spam_protection_enabled INTEGER DEFAULT 0",
        "ALTER TABLE guild_settings ADD COLUMN bad_words TEXT DEFAULT ''",
        "ALTER TABLE guild_settings ADD COLUMN afk_move_enabled INTEGER DEFAULT 0"
    ]:
        try:
            await conn.execute(col_query)
        except Exception:
            pass

    # Firewall Sync with Bot IPC
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            mode = "on" if firewall_enabled == "1" else "off"
            res = await client.post(
                f"http://127.0.0.1:8001/api/guild/{target_guild_id}/firewall",
                json={"mode": mode, "actor_id": user["id"]}
            )
            if res.status_code != 200:
                log.error(f"Failed to sync firewall status with bot: {res.text}")
    except Exception as e:
        log.error(f"Firewall state IPC sync error: {e}")

    await conn.execute(
        """
        INSERT INTO guild_settings (guild_id, automod_enabled, firewall_enabled, spam_protection_enabled, bad_words, afk_move_enabled)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            automod_enabled = excluded.automod_enabled,
            firewall_enabled = excluded.firewall_enabled,
            spam_protection_enabled = excluded.spam_protection_enabled,
            bad_words = excluded.bad_words,
            afk_move_enabled = excluded.afk_move_enabled
        """,
        (
            target_guild_id,
            int(automod_enabled),
            int(firewall_enabled),
            int(spam_protection_enabled),
            bad_words,
            int(afk_move_enabled),
        ),
    )
    await conn.commit()
    await conn.close()
    
    return RedirectResponse(f"/dashboard/{guild_id}/automod?success=1", status_code=303)


@app.post("/dashboard/{guild_id}/settings/welcome/simulate")
async def simulate_welcome(request: Request, guild_id: str):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    discord_id = user["id"]
    
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.post(
                f"http://127.0.0.1:8001/api/guild/{target_guild_id}/simulate_welcome",
                json={"user_id": discord_id}
            )
            if res.status_code != 200:
                log.error(f"Failed to simulate welcome: {res.text}")
    except Exception as e:
        log.error(f"Simulator IPC error: {e}")

    return RedirectResponse(f"/dashboard/{guild_id}/welcome?simulated=1", status_code=303)


@app.post("/dashboard/{guild_id}/broadcast")
async def do_broadcast(
    request: Request,
    guild_id: str,
    channel_id: str = Form(""),
    title: str = Form(""),
    message: str = Form(""),
    color: str = Form(""),
):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    if not message or not channel_id:
        return RedirectResponse(f"/dashboard/{guild_id}/broadcast", status_code=303)

    conn = await get_db()
    try:
        await conn.execute("ALTER TABLE scheduled_announcements ADD COLUMN title TEXT DEFAULT '⚠ Network-Wide Broadcast'")
        await conn.execute("ALTER TABLE scheduled_announcements ADD COLUMN color TEXT DEFAULT '#00FFFF'")
        await conn.execute("ALTER TABLE scheduled_announcements ADD COLUMN instant INTEGER DEFAULT 0")
    except Exception:
        pass

    import time
    run_at = int(time.time())
    
    await conn.execute(
        """
        INSERT INTO scheduled_announcements (guild_id, channel_id, message, title, color, run_at, sent, instant)
        VALUES (?, ?, ?, ?, ?, ?, 0, 1)
        """,
        (target_guild_id, int(channel_id), message, title, color, run_at),
    )
    await conn.commit()
    
    # Save the default channel if it's the first time
    await conn.execute(
        """
        INSERT INTO guild_settings (guild_id, default_announce_id) VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET default_announce_id = excluded.default_announce_id
        """,
        (target_guild_id, int(channel_id))
    )
    await conn.commit()
    await conn.close()

    return RedirectResponse(f"/dashboard/{guild_id}/broadcast?success=1", status_code=303)


@app.post("/dashboard/{guild_id}/settings/updates_channel")
async def save_updates_channel(
    request: Request,
    guild_id: str,
    updates_channel_id: str = Form(""),
):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    conn = await get_db()
    
    try:
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN updates_channel_id INTEGER")
    except Exception:
        pass

    await conn.execute(
        """
        INSERT INTO guild_settings (guild_id, updates_channel_id)
        VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            updates_channel_id = excluded.updates_channel_id
        """,
        (
            target_guild_id,
            int(updates_channel_id) if updates_channel_id else None,
        ),
    )
    await conn.commit()
    await conn.close()
    return RedirectResponse(f"/dashboard/{guild_id}/broadcast?success_updates=1", status_code=303)


@app.get("/dashboard/{guild_id}/custom_commands", response_class=HTMLResponse)
async def dashboard_custom_commands_page(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)
    bot_guild_data = get_bot_guild_data(target_guild_id)

    conn = await aiosqlite.connect(DB_PATH)
    cursor = await conn.execute("SELECT id, trigger, response_content FROM custom_commands WHERE guild_id = ? ORDER BY id DESC", (target_guild_id,))
    commands_rows = await cursor.fetchall()
    
    commands_list = []
    for row in commands_rows:
        commands_list.append({
            "id": row[0],
            "trigger": row[1],
            "response_content": row[2]
        })
    await conn.close()

    success = request.query_params.get("success")
    return templates.TemplateResponse(
        "custom_commands.html",
        {
            "request": request,
            "guild": guild,
            "bot_guild": bot_guild_data,
            "user": user,
            "commands_list": commands_list,
            "success": success,
        }
    )

@app.post("/dashboard/{guild_id}/custom_commands/add")
async def add_custom_command(request: Request, guild_id: str, trigger: str = Form(...), response_content: str = Form(...)):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)
    trigger = trigger.strip()
    response_content = response_content.strip()

    if not trigger or not response_content:
        return RedirectResponse(f"/dashboard/{guild_id}/custom_commands", status_code=303)

    conn = await aiosqlite.connect(DB_PATH)
    await conn.execute("INSERT INTO custom_commands (guild_id, trigger, response_content) VALUES (?, ?, ?)", (target_guild_id, trigger, response_content))
    await conn.commit()
    await conn.close()

    return RedirectResponse(f"/dashboard/{guild_id}/custom_commands?success=1", status_code=303)

@app.post("/dashboard/{guild_id}/custom_commands/delete")
async def delete_custom_command(request: Request, guild_id: str, command_id: int = Form(...)):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)

    conn = await aiosqlite.connect(DB_PATH)
    await conn.execute("DELETE FROM custom_commands WHERE id = ? AND guild_id = ?", (command_id, target_guild_id))
    await conn.commit()
    await conn.close()

    return RedirectResponse(f"/dashboard/{guild_id}/custom_commands?success=1", status_code=303)


@app.get("/dashboard/{guild_id}/reaction_roles", response_class=HTMLResponse)
async def dashboard_reaction_roles_page(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)
    bot_guild_data = get_bot_guild_data(target_guild_id)

    conn = await aiosqlite.connect(DB_PATH)
    cursor = await conn.execute("SELECT message_id, channel_id, roles_json FROM reaction_role_panels WHERE guild_id = ? ORDER BY id DESC", (target_guild_id,))
    panels_rows = await cursor.fetchall()
    
    panels_list = []
    for row in panels_rows:
        try:
            import json
            roles_data = json.loads(row[2])
        except Exception:
            roles_data = []
        panels_list.append({
            "message_id": row[0],
            "channel_id": row[1],
            "roles_data": roles_data
        })
    await conn.close()

    success = request.query_params.get("success")
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "reaction_roles.html",
        {
            "request": request,
            "guild": guild,
            "bot_guild": bot_guild_data,
            "user": user,
            "panels_list": panels_list,
            "success": success,
            "error": error
        }
    )

@app.post("/dashboard/{guild_id}/reaction_roles/deploy")
async def deploy_reaction_roles(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    form_data = await request.form()
    channel_id = form_data.get("channel_id")
    panel_title = form_data.get("panel_title")
    panel_desc = form_data.get("panel_desc")
    
    # We expect dynamic inputs like role_id_1, label_1, emoji_1, style_1
    roles_data = []
    for i in range(1, 10):
        r_id = form_data.get(f"role_id_{i}")
        if r_id:
            roles_data.append({
                "role_id": int(r_id),
                "label": form_data.get(f"label_{i}", "Role"),
                "emoji": form_data.get(f"emoji_{i}", ""),
                "style": form_data.get(f"style_{i}", "primary")
            })

    if not channel_id or not roles_data:
        return RedirectResponse(f"/dashboard/{guild_id}/reaction_roles?error=Missing+parameters", status_code=303)

    payload = {
        "channel_id": int(channel_id),
        "title": panel_title or "Pick Your Roles",
        "description": panel_desc or "Click the buttons below to seamlessly toggle your server roles!",
        "roles_data": roles_data
    }

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{BOT_API_URL}/api/guild/{guild_id}/reaction_roles", json=payload, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return RedirectResponse(f"/dashboard/{guild_id}/reaction_roles?success=1", status_code=303)
                else:
                    err = data.get("error", "Unknown Bot Error")
                    return RedirectResponse(f"/dashboard/{guild_id}/reaction_roles?error={err}", status_code=303)
            else:
                return RedirectResponse(f"/dashboard/{guild_id}/reaction_roles?error=Bot+returned+{resp.status_code}", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/dashboard/{guild_id}/reaction_roles?error=Bot+API+Offline", status_code=303)


@app.get("/dashboard/{guild_id}/tickets", response_class=HTMLResponse)
async def dashboard_tickets_page(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    guild = get_guild_from_session(user, guild_id)
    if not guild:
         return HTMLResponse("Unauthorized", status_code=403)

    target_guild_id = int(guild_id)
    bot_data = await get_bot_guild_data(target_guild_id)

    conn = await get_db()
    try:
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN ticket_category_id INTEGER")
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN ticket_role_id INTEGER")
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN ticket_log_channel_id INTEGER")
    except Exception:
        pass

    cur = await conn.execute(
        "SELECT ticket_category_id, ticket_role_id, ticket_log_channel_id FROM guild_settings WHERE guild_id = ?",
        (target_guild_id,),
    )
    row = await cur.fetchone()
    await conn.close()
    
    import json
    ticket_roles = []
    if row and row["ticket_role_id"]:
        try:
            val = row["ticket_role_id"]
            if isinstance(val, int):
                ticket_roles = [str(val)]
            else:
                ticket_roles = json.loads(val)
        except (ValueError, TypeError):
            ticket_roles = [str(row["ticket_role_id"])]
    
    data = {
        "ticket_category_id": str(row["ticket_category_id"]) if row and row["ticket_category_id"] else "",
        "ticket_roles": ticket_roles,
        "ticket_log_channel_id": str(row["ticket_log_channel_id"]) if row and row["ticket_log_channel_id"] else "",
    }

    return templates.TemplateResponse("tickets.html", {
        "request": request,
        "user": user,
        "guild": guild,
        "bot_data": bot_data,
        "data": data,
        "active_page": "tickets"
    })

@app.post("/dashboard/{guild_id}/settings/tickets")
async def save_tickets(
    request: Request,
    guild_id: str,
    ticket_category_id: str = Form(""),
    ticket_role_ids: list[str] = Form(default=[]),
    ticket_log_channel_id: str = Form(""),
):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    conn = await get_db()
    
    try:
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN ticket_category_id INTEGER")
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN ticket_role_id TEXT")
        await conn.execute("ALTER TABLE guild_settings ADD COLUMN ticket_log_channel_id INTEGER")
    except Exception:
        pass

    import json
    clean_roles = [r for r in ticket_role_ids if r.strip()]
    roles_json = json.dumps(clean_roles) if clean_roles else None

    await conn.execute(
        """
        INSERT INTO guild_settings (guild_id, ticket_category_id, ticket_role_id, ticket_log_channel_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            ticket_category_id = excluded.ticket_category_id,
            ticket_role_id = excluded.ticket_role_id,
            ticket_log_channel_id = excluded.ticket_log_channel_id
        """,
        (
            target_guild_id,
            int(ticket_category_id) if ticket_category_id else None,
            roles_json,
            int(ticket_log_channel_id) if ticket_log_channel_id else None,
        ),
    )
    await conn.commit()
    await conn.close()
    return RedirectResponse(f"/dashboard/{guild_id}/tickets?success=1", status_code=303)

# ---------- AI Assistant ----------

@app.get("/dashboard/{guild_id}/ai", response_class=HTMLResponse)
async def dashboard_ai_page(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return HTMLResponse("Unauthorized", status_code=403)

    target_guild_id = int(guild_id)
    conn = await get_db()
    
    for col_query in [
        "ALTER TABLE guild_settings ADD COLUMN ai_channel_id INTEGER",
        "ALTER TABLE guild_settings ADD COLUMN ai_personality TEXT DEFAULT 'You are a short, cyber-security themed Discord assistant.'",
        "ALTER TABLE guild_settings ADD COLUMN ai_temperature REAL DEFAULT 0.7"
    ]:
        try:
            await conn.execute(col_query)
        except Exception:
            pass

    cur = await conn.execute(
        "SELECT ai_channel_id, ai_personality, ai_temperature FROM guild_settings WHERE guild_id = ?",
        (target_guild_id,),
    )
    row = await cur.fetchone()
    await conn.close()
    
    bot_data = await get_bot_guild_data(target_guild_id)

    data = {
        "ai_channel_id": str(row["ai_channel_id"]) if row and row["ai_channel_id"] else "",
        "ai_personality": row["ai_personality"] if row and row["ai_personality"] else "You are a short, cyber-security themed Discord assistant.",
        "ai_temperature": row["ai_temperature"] if row and row["ai_temperature"] is not None else 0.7,
    }

    return templates.TemplateResponse("ai.html", {
        "request": request,
        "user": user,
        "guild": guild,
        "bot_data": bot_data,
        "data": data,
        "active_page": "ai"
    })

@app.post("/dashboard/{guild_id}/settings/ai")
async def save_ai_settings(
    request: Request,
    guild_id: str,
    ai_channel_id: str = Form(""),
    ai_personality: str = Form(""),
    ai_temperature: float = Form(0.7),
):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    conn = await get_db()
    
    for col_query in [
        "ALTER TABLE guild_settings ADD COLUMN ai_channel_id INTEGER",
        "ALTER TABLE guild_settings ADD COLUMN ai_personality TEXT DEFAULT 'You are a short, cyber-security themed Discord assistant.'",
        "ALTER TABLE guild_settings ADD COLUMN ai_temperature REAL DEFAULT 0.7"
    ]:
        try:
            await conn.execute(col_query)
        except Exception:
            pass

    await conn.execute(
        """
        INSERT INTO guild_settings (guild_id, ai_channel_id, ai_personality, ai_temperature)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            ai_channel_id = excluded.ai_channel_id,
            ai_personality = excluded.ai_personality,
            ai_temperature = excluded.ai_temperature
        """,
        (
            target_guild_id,
            int(ai_channel_id) if ai_channel_id else None,
            ai_personality.strip(),
            ai_temperature,
        ),
    )
    await conn.commit()
    await conn.close()
    return RedirectResponse(f"/dashboard/{guild_id}/ai?success=1", status_code=303)


# ---------- YouTube Notifications ----------

@app.get("/dashboard/{guild_id}/youtube", response_class=HTMLResponse)
async def dashboard_youtube_page(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)
    bot_guild_data = await get_bot_guild_data(target_guild_id)

    conn = await get_db()
    cursor = await conn.execute("SELECT id, channel_id, youtube_channel_id FROM youtube_notifications WHERE guild_id = ? ORDER BY id DESC", (target_guild_id,))
    trackers_rows = await cursor.fetchall()
    
    # Map discord channel IDs to names for the UI
    channel_map = {str(c["id"]): c["name"] for c in bot_guild_data.get("channels", [])}
    
    trackers = []
    for row in trackers_rows:
        discord_channel_id = str(row["channel_id"])
        discord_channel_name = channel_map.get(discord_channel_id, discord_channel_id)
        
        trackers.append({
            "id": row["id"],
            "discord_channel_id": discord_channel_id,
            "discord_channel_name": f"#{discord_channel_name}",
            "youtube_channel_id": row["youtube_channel_id"]
        })
    await conn.close()

    return templates.TemplateResponse(
        "youtube.html",
        {
            "request": request,
            "guild": guild,
            "bot_guild": bot_guild_data,
            "user": user,
            "trackers": trackers,
            "active_page": "youtube"
        }
    )

@app.post("/dashboard/{guild_id}/youtube/add")
async def add_youtube_tracker(request: Request, guild_id: str, youtube_channel_id: str = Form(""), channel_id: str = Form("")):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)
    youtube_channel_id = youtube_channel_id.strip()

    if not youtube_channel_id or not channel_id:
        return RedirectResponse(f"/dashboard/{guild_id}/youtube?error=Missing+parameters", status_code=303)

    if not youtube_channel_id.startswith("UC") or len(youtube_channel_id) != 24:
        return RedirectResponse(f"/dashboard/{guild_id}/youtube?error=Invalid+YouTube+Channel+ID+format.+Must+start+with+UC+and+be+24+characters+long.", status_code=303)

    conn = await get_db()
    # Check if already exists
    cur = await conn.execute("SELECT id FROM youtube_notifications WHERE guild_id = ? AND youtube_channel_id = ?", (target_guild_id, youtube_channel_id))
    if await cur.fetchone():
        await conn.close()
        return RedirectResponse(f"/dashboard/{guild_id}/youtube?error=Channel+is+already+being+tracked.", status_code=303)

    await conn.execute("INSERT INTO youtube_notifications (guild_id, channel_id, youtube_channel_id, last_video_id) VALUES (?, ?, ?, ?)", 
                       (target_guild_id, int(channel_id), youtube_channel_id, None))
    await conn.commit()
    await conn.close()

    return RedirectResponse(f"/dashboard/{guild_id}/youtube?success=1", status_code=303)


@app.post("/dashboard/{guild_id}/youtube/remove")
async def remove_youtube_tracker(request: Request, guild_id: str, youtube_channel_id: str = Form(...)):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)

    conn = await get_db()
    await conn.execute("DELETE FROM youtube_notifications WHERE guild_id = ? AND youtube_channel_id = ?", (target_guild_id, youtube_channel_id))
    await conn.commit()
    await conn.close()

    return RedirectResponse(f"/dashboard/{guild_id}/youtube?success=1", status_code=303)
# ---------- Mod Logs ----------

@app.get("/dashboard/{guild_id}/mod_logs", response_class=HTMLResponse)
async def dashboard_mod_logs(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)
    bot_guild_data = await get_bot_guild_data(target_guild_id)

    conn = await get_db()
    # Fetch warnings
    cur = await conn.execute("SELECT id, user_id, actor_id, reason, created_at FROM warnings WHERE guild_id = ? ORDER BY created_at DESC LIMIT 100", (target_guild_id,))
    warnings = await cur.fetchall()
    
    # Try fetching moderation_logs if it exists
    mod_actions = []
    try:
        cur2 = await conn.execute("SELECT id, action, user_id, moderator_id, reason, timestamp FROM moderation_logs WHERE guild_id=? ORDER BY timestamp DESC LIMIT 100", (target_guild_id,))
        mod_actions = await cur2.fetchall()
    except Exception:
        pass
    
    await conn.close()

    return templates.TemplateResponse(
        "mod_logs.html",
        {
            "request": request,
            "guild": guild,
            "bot_guild": bot_guild_data,
            "user": user,
            "warnings": warnings,
            "mod_actions": mod_actions,
            "active_page": "mod_logs"
        }
    )

# ---------- Economy Shop Editor ----------

@app.get("/dashboard/{guild_id}/shop", response_class=HTMLResponse)
async def dashboard_shop(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)
    bot_guild_data = await get_bot_guild_data(target_guild_id)

    conn = await get_db()
    cur = await conn.execute("SELECT id, name, price, role_id FROM economy_shop WHERE guild_id = ? ORDER BY price ASC", (target_guild_id,))
    shop_items = await cur.fetchall()
    await conn.close()

    # Get roles from IPC for the dropdown
    roles = []
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"http://127.0.0.1:8001/api/guild/{target_guild_id}/roles")
            if res.status_code == 200:
                roles = res.json().get("roles", [])
    except Exception:
        pass

    return templates.TemplateResponse(
        "shop_editor.html",
        {
            "request": request,
            "guild": guild,
            "bot_guild": bot_guild_data,
            "user": user,
            "shop_items": shop_items,
            "roles": roles,
            "active_page": "shop"
        }
    )

@app.post("/dashboard/{guild_id}/shop/add")
async def dashboard_shop_add(request: Request, guild_id: str, name: str = Form(...), price: int = Form(...), role_id: str = Form(...)):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    if not name or price <= 0 or not role_id:
        return RedirectResponse(f"/dashboard/{guild_id}/shop?error=Invalid+inputs", status_code=303)

    conn = await get_db()
    await conn.execute("INSERT INTO economy_shop (guild_id, name, price, role_id) VALUES (?, ?, ?, ?)", (target_guild_id, name, price, int(role_id)))
    await conn.commit()
    await conn.close()

    return RedirectResponse(f"/dashboard/{guild_id}/shop?success=Item+Added", status_code=303)

@app.post("/dashboard/{guild_id}/shop/delete")
async def dashboard_shop_delete(request: Request, guild_id: str, item_id: int = Form(...)):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    conn = await get_db()
    await conn.execute("DELETE FROM economy_shop WHERE guild_id = ? AND id = ?", (target_guild_id, item_id))
    await conn.commit()
    await conn.close()

    return RedirectResponse(f"/dashboard/{guild_id}/shop?success=Item+Deleted", status_code=303)


# ---------- System Controls ----------

@app.get("/dashboard/{guild_id}/system", response_class=HTMLResponse)
async def dashboard_system_page(request: Request, guild_id: str):
    user = require_login(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    guild = get_guild_from_session(user, guild_id)
    if not guild:
        return RedirectResponse("/dashboard", status_code=303)

    target_guild_id = int(guild_id)
    bot_guild_data = await get_bot_guild_data(target_guild_id)

    # Fetch system stats from Bot IPC
    sys_metrics = {
        "ram_mb": 0.0,
        "cpu_percent": 0.0,
        "uptime_str": "Unknown",
        "ping": 0
    }
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            # Added a slash before system to avoid 404
            res = await client.get(f"http://127.0.0.1:8001/api/guild/{target_guild_id}/system")
            if res.status_code == 200:
                sys_metrics = res.json()
    except Exception as e:
        log.warning(f"Failed to fetch system metrics: {e}")

    return templates.TemplateResponse(
        "system.html",
        {
            "request": request,
            "guild": guild,
            "bot_guild": bot_guild_data,
            "user": user,
            "sys_metrics": sys_metrics,
            "active_page": "system"
        }
    )

@app.post("/dashboard/{guild_id}/system/restart")
async def system_restart(request: Request, guild_id: str):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"http://127.0.0.1:8001/api/guild/{target_guild_id}/control/restart")
    except httpx.ReadTimeout:
        # Expected since the bot restarts itself during the request
        pass
    except Exception as e:
        log.error(f"Failed to IPC restart: {e}")
        return RedirectResponse(f"/dashboard/{guild_id}/system?error=Failed+to+communicate+with+system+core.", status_code=303)

    return RedirectResponse(f"/dashboard/{guild_id}/system?success=System+Core+is+Rebooting.", status_code=303)


@app.post("/dashboard/{guild_id}/system/shutdown")
async def system_shutdown(request: Request, guild_id: str):
    user = require_login(request)
    if not user or not get_guild_from_session(user, guild_id):
        return RedirectResponse("/login", status_code=303)

    target_guild_id = int(guild_id)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(f"http://127.0.0.1:8001/api/guild/{target_guild_id}/control/shutdown")
    except httpx.ReadTimeout:
        pass
    except Exception as e:
        log.error(f"Failed to IPC shutdown: {e}")
        return RedirectResponse(f"/dashboard/{guild_id}/system?error=Failed+to+communicate+with+system+core.", status_code=303)

    return RedirectResponse(f"/dashboard/{guild_id}/system?success=Emergency+Shutdown+Triggered.+Manual+Start+Required.", status_code=303)
