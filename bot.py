# bot.py
import os
import sys
import time
import psutil
from typing import Optional

import discord
from discord.ext import commands
import aiosqlite
import logging

from config import TOKEN, GUILD_ID, DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("ultimatebot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("UltimateBot")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class UltimateBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )
        self.db: Optional[aiosqlite.Connection] = None
        self.tree.on_error = self.on_app_command_error

    async def setup_hook(self) -> None:
        # Ensure data dir
        os.makedirs("data", exist_ok=True)

        # Database
        self.db = await aiosqlite.connect(DB_PATH)
        await self._init_db()

        # Load cogs
        for ext in (
            "cogs.admin",
            "cogs.welcome",
            "cogs.backups",
            "cogs.tickets",
            "cogs.fun",
            "cogs.automod",      
            "cogs.moderation",   
            "cogs.ai",           
            "cogs.help",         
            "cogs.voice_logs",   
            "cogs.levels",       
            "cogs.custom_commands", 
            "cogs.reaction_roles",  
            "cogs.afk",          
            "cogs.youtube",      
            "cogs.birthday",     
            "cogs.moderation_extended", 
            "cogs.stats_channels", 
            "cogs.music",        
            "cogs.soundboard",   
            "cogs.giveaway",
            "cogs.economy",
            "cogs.starboard",
            "cogs.warnings",
            "cogs.games",
            "cogs.streaks",
            "cogs.quotes",
            "cogs.counting",
            "cogs.reminders",
            "cogs.invite_tracker",
            "cogs.security_advanced",
            "cogs.casino",
            "cogs.rpg",
            "cogs.marriage",
            "cogs.j2c",
            "cogs.roleplay",
            "cogs.image_memes",
        ):
            await self.load_extension(ext)
            
        # Start IPC Server for Dashboard
        self.loop.create_task(self.start_ipc_server())

        # --- CHANGED: Removed automatic syncing to prevent Rate Limits ---
        log.info("[SYNC] Skipped automatic sync to prevent API bans.")
        log.info("Use the '!sync' command in Discord to update slash commands manually.")

    async def _init_db(self):
        assert self.db is not None
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id            INTEGER PRIMARY KEY,
                welcome_channel_id  INTEGER,
                welcome_message     TEXT,
                welcome_title       TEXT DEFAULT '🚨 New Operative Connected',
                welcome_color       TEXT DEFAULT '#E74C3C',
                welcome_image_url   TEXT,
                autorole_id         INTEGER,
                default_announce_id INTEGER,
                updates_channel_id  INTEGER
            );

            CREATE TABLE IF NOT EXISTS scheduled_announcements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER,
                channel_id  INTEGER,
                message     TEXT,
                title       TEXT DEFAULT '⚠ Network-Wide Broadcast',
                color       TEXT DEFAULT '#00FFFF',
                run_at      INTEGER,
                sent        INTEGER DEFAULT 0,
                instant     INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS moderation_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER,
                user_id     INTEGER,
                actor_id    INTEGER,
                action      TEXT,
                reason      TEXT,
                created_at  INTEGER
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id        INTEGER,
                channel_id      INTEGER,
                opener_id       INTEGER,
                status          TEXT,
                created_at      INTEGER,
                closed_at       INTEGER
            );

            CREATE TABLE IF NOT EXISTS voice_stats (
                user_id INTEGER,
                guild_id INTEGER,
                total_seconds REAL DEFAULT 0.0,
                PRIMARY KEY (user_id, guild_id)
            );

            CREATE TABLE IF NOT EXISTS youtube_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                youtube_channel_id TEXT,
                last_video_id TEXT
            );
            
            CREATE TABLE IF NOT EXISTS restart_flags (
                guild_id INTEGER PRIMARY KEY,
                pending INTEGER DEFAULT 0,
                features TEXT,
                channel_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS birthdays (
                user_id  INTEGER,
                guild_id INTEGER,
                month    INTEGER,
                day      INTEGER,
                PRIMARY KEY (user_id, guild_id)
            );

            CREATE TABLE IF NOT EXISTS stats_channels (
                guild_id        INTEGER PRIMARY KEY,
                category_id     INTEGER,
                members_channel INTEGER,
                online_channel  INTEGER,
                boosts_channel  INTEGER
            );

            CREATE TABLE IF NOT EXISTS economy (user_id INT, guild_id INT, coins INT DEFAULT 0, last_daily INT, PRIMARY KEY(user_id, guild_id));
            CREATE TABLE IF NOT EXISTS economy_shop (id INTEGER PRIMARY KEY, guild_id INT, name TEXT, price INT, role_id INT);
            CREATE TABLE IF NOT EXISTS warnings (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INT, user_id INT, actor_id INT, reason TEXT, created_at INT);
            CREATE TABLE IF NOT EXISTS warning_config (guild_id INT PRIMARY KEY, mute_at INT DEFAULT 3, kick_at INT DEFAULT 5, ban_at INT DEFAULT 7);
            CREATE TABLE IF NOT EXISTS starboard_config (guild_id INT PRIMARY KEY, channel_id INT, threshold INT DEFAULT 3);
            CREATE TABLE IF NOT EXISTS starboard_posts (original_msg_id INT PRIMARY KEY, starboard_msg_id INT, guild_id INT);
            CREATE TABLE IF NOT EXISTS giveaways (id INTEGER PRIMARY KEY, guild_id INT, channel_id INT, message_id INT, prize TEXT, winners INT, ends_at INT, ended INT DEFAULT 0);
            CREATE TABLE IF NOT EXISTS quotes (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INT, user_id INT, quoted_user_id INT, content TEXT, created_at INT);
            CREATE TABLE IF NOT EXISTS counting (guild_id INT PRIMARY KEY, channel_id INT, current_count INT DEFAULT 0, last_user_id INT);
            CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, channel_id INT, message TEXT, remind_at INT, done INT DEFAULT 0);
            CREATE TABLE IF NOT EXISTS invite_tracker (invite_code TEXT, guild_id INT, inviter_id INT, uses INT DEFAULT 0, PRIMARY KEY(invite_code, guild_id));
            CREATE TABLE IF NOT EXISTS member_invites (user_id INT, guild_id INT, invited_by INT, PRIMARY KEY(user_id, guild_id));
            CREATE TABLE IF NOT EXISTS streaks (user_id INT, guild_id INT, current_streak INT DEFAULT 0, best_streak INT DEFAULT 0, last_message_date TEXT, PRIMARY KEY(user_id, guild_id));
            CREATE TABLE IF NOT EXISTS scam_domains (guild_id INT, domain TEXT, PRIMARY KEY(guild_id, domain));
            CREATE TABLE IF NOT EXISTS pets (user_id INT PRIMARY KEY, name TEXT, type TEXT, level INT, exp INT);
            CREATE TABLE IF NOT EXISTS marriages (user1_id INT, user2_id INT, married_at INT);
            CREATE TABLE IF NOT EXISTS j2c_config (guild_id INT PRIMARY KEY, master_channel_id INT, category_id INT);
            CREATE TABLE IF NOT EXISTS j2c_channels (channel_id INT PRIMARY KEY, owner_id INT);
            CREATE TABLE IF NOT EXISTS anti_nuke_config (guild_id INT PRIMARY KEY, messages INT, seconds INT);
            """
        )
        
        for col_query in [
            "ALTER TABLE guild_settings ADD COLUMN updates_channel_id INTEGER",
            "ALTER TABLE guild_settings ADD COLUMN afk_move_enabled INTEGER DEFAULT 0",
            "ALTER TABLE guild_settings ADD COLUMN automod_enabled INTEGER DEFAULT 0",
            "ALTER TABLE guild_settings ADD COLUMN firewall_enabled INTEGER DEFAULT 0",
            "ALTER TABLE guild_settings ADD COLUMN spam_protection_enabled INTEGER DEFAULT 0",
            "ALTER TABLE guild_settings ADD COLUMN bad_words TEXT DEFAULT ''",
            "ALTER TABLE guild_settings ADD COLUMN voice_log_channel_id INTEGER",
            "ALTER TABLE guild_settings ADD COLUMN ai_channel_id INTEGER",
            "ALTER TABLE guild_settings ADD COLUMN ai_personality TEXT DEFAULT 'You are a short, cyber-security themed Discord assistant.'",
            "ALTER TABLE guild_settings ADD COLUMN ai_temperature REAL DEFAULT 0.7",
            "ALTER TABLE restart_flags ADD COLUMN channel_id INTEGER",
            "ALTER TABLE guild_settings ADD COLUMN birthday_channel_id INTEGER"
        ]:
            try:
                await self.db.execute(col_query)
            except Exception:
                pass

        await self.db.commit()

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandNotFound):
            return
        log.error(f"Ignoring exception in command {ctx.command}:", exc_info=error)
        try:
            await ctx.send(f"An error occurred: {error}")
        except discord.DiscordException:
            pass

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        log.error(f"Exception in slash command '{interaction.command.name}':", exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"An error occurred: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"An error occurred: {error}", ephemeral=True)
        except discord.DiscordException:
            pass

    async def start_ipc_server(self):
        from aiohttp import web
        app = web.Application()
        app.add_routes([
            web.get('/api/guild/{guild_id}', self.handle_ipc_guild),
            web.post('/api/guild/{guild_id}/simulate_welcome', self.handle_ipc_simulate_welcome),
            web.post('/api/guild/{guild_id}/firewall', self.handle_ipc_firewall),
            web.post('/api/guild/{guild_id}/reaction_roles', self.handle_ipc_reaction_roles),
            web.get('/api/guild/{guild_id}/system', self.handle_ipc_system),
            web.post('/api/guild/{guild_id}/control/restart', self.handle_ipc_restart),
            web.post('/api/guild/{guild_id}/control/shutdown', self.handle_ipc_shutdown)
        ])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 8001)
        await site.start()
        log.info("[IPC] Internal API server started on port 8001")

    async def handle_ipc_guild(self, request):
        try:
            guild_id = int(request.match_info['guild_id'])
        except ValueError:
            from aiohttp import web
            return web.json_response({"error": "Invalid guild ID"}, status=400)
            
        guild = self.get_guild(guild_id)
        if not guild:
            from aiohttp import web
            return web.json_response({"error": "Guild not found"}, status=404)
            
        channels = [{"id": str(c.id), "name": c.name, "type": str(c.type)} for c in guild.channels if isinstance(c, discord.TextChannel)]
        categories = [{"id": str(c.id), "name": c.name} for c in guild.categories]
        roles = [{"id": str(r.id), "name": r.name, "color": str(r.color)} for r in guild.roles if r.name != "@everyone"]
        
        from aiohttp import web
        return web.json_response({
            "name": guild.name,
            "id": str(guild.id),
            "channels": channels,
            "categories": categories,
            "roles": roles,
            "member_count": guild.member_count
        })

    async def handle_ipc_simulate_welcome(self, request):
        try:
            guild_id = int(request.match_info['guild_id'])
            data = await request.json()
            user_id = int(data.get("user_id"))
        except (ValueError, TypeError):
            from aiohttp import web
            return web.json_response({"error": "Invalid guild ID or User ID"}, status=400)
            
        guild = self.get_guild(guild_id)
        if not guild:
            from aiohttp import web
            return web.json_response({"error": "Guild not found"}, status=404)
            
        member = guild.get_member(user_id)
        if not member:
            from aiohttp import web
            return web.json_response({"error": "Member not in guild"}, status=404)
            
        welcome_cog = self.get_cog("WelcomeCog")
        if not welcome_cog:
            from aiohttp import web
            return web.json_response({"error": "WelcomeCog not loaded"}, status=500)
            
        self.loop.create_task(welcome_cog.on_member_join(member))
        
        from aiohttp import web
        return web.json_response({"success": True})

    async def handle_ipc_firewall(self, request):
        try:
            guild_id = int(request.match_info['guild_id'])
            data = await request.json()
            mode = data.get("mode")
            actor_id = int(data.get("actor_id")) if data.get("actor_id") else None
        except (ValueError, TypeError):
            from aiohttp import web
            return web.json_response({"error": "Invalid payload"}, status=400)
            
        guild = self.get_guild(guild_id)
        if not guild:
            from aiohttp import web
            return web.json_response({"error": "Guild not found"}, status=404)
            
        automod_cog = self.get_cog("AutoModCog")
        if not automod_cog:
            from aiohttp import web
            return web.json_response({"error": "AutoModCog not loaded"}, status=500)
            
        if mode == "on":
            self.loop.create_task(automod_cog.enable_firewall(guild, "Dashboard manual enable", actor_id))
        elif mode == "off":
            self.loop.create_task(automod_cog.disable_firewall(guild, actor_id))
            
        from aiohttp import web
        return web.json_response({"success": True})

    async def handle_ipc_reaction_roles(self, request):
        try:
            guild_id = int(request.match_info['guild_id'])
            data = await request.json()
        except (ValueError, TypeError):
            from aiohttp import web
            return web.json_response({"error": "Invalid payload"}, status=400)

        guild = self.get_guild(guild_id)
        if not guild:
            from aiohttp import web
            return web.json_response({"error": "Guild not found"}, status=404)

        channel_id = data.get("channel_id")
        channel = guild.get_channel(channel_id)
        if not channel:
            from aiohttp import web
            return web.json_response({"error": "Destination channel not found"}, status=404)
        
        from cogs.reaction_roles import ReactionRoleView
        import json
        
        roles_data = data.get("roles_data", [])
        if not roles_data:
            from aiohttp import web
            return web.json_response({"error": "No roles provided"}, status=400)

        embed = discord.Embed(
            title=data.get("title", "Select Roles"),
            description=data.get("description", "Click the buttons below to toggle your roles!"),
            color=discord.Color.blue()
        )
        
        view = ReactionRoleView(roles_data)
        
        async def send_and_save():
            try:
                msg = await channel.send(embed=embed, view=view)
                if getattr(self, "db", None):
                    await self.db.execute(
                        "INSERT INTO reaction_role_panels (guild_id, channel_id, message_id, roles_json) VALUES (?, ?, ?, ?)",
                        (guild.id, channel.id, msg.id, json.dumps(roles_data))
                    )
                    await self.db.commit()
            except Exception as e:
                import logging
                logging.error(f"[ReactionRoles] Failed to deploy panel: {e}")

        self.loop.create_task(send_and_save())
        
        from aiohttp import web
        return web.json_response({"success": True})

    async def handle_ipc_system(self, request):
        from aiohttp import web
        import asyncio
        try:
            guild_id = int(request.match_info['guild_id'])
            guild = self.get_guild(guild_id)
            if not guild:
                return web.json_response({"error": "Guild not found"}, status=404)
        except ValueError:
            return web.json_response({"error": "Invalid guild ID"}, status=400)

        process = psutil.Process(os.getpid())
        ram_mb = process.memory_info().rss / 1024 / 1024
        
        process.cpu_percent(interval=None)
        await asyncio.sleep(0.1)
        cpu_perc = process.cpu_percent(interval=None)
        
        uptime_s = time.time() - process.create_time()
        ping_ms = round(self.latency * 1000)

        m, s = divmod(int(uptime_s), 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        
        if d > 0:
            uptime_str = f"{d}d {h}h {m}m {s}s"
        elif h > 0:
            uptime_str = f"{h}h {m}m {s}s"
        else:
            uptime_str = f"{m}m {s}s"

        return web.json_response({
            "ram_mb": round(ram_mb, 1),
            "cpu_percent": round(cpu_perc, 1),
            "uptime_str": uptime_str,
            "ping": ping_ms
        })

    async def handle_ipc_restart(self, request):
        from aiohttp import web
        import asyncio
        try:
            guild_id = int(request.match_info['guild_id'])
            guild = self.get_guild(guild_id)
            if not guild:
                return web.json_response({"error": "Guild not found"}, status=404)
        except ValueError:
            return web.json_response({"error": "Invalid guild ID"}, status=400)

        cursor = await self.db.execute("SELECT updates_channel_id FROM guild_settings WHERE guild_id = ?", (guild.id,))
        row = await cursor.fetchone()
        updates_channel_id = row[0] if row and row[0] else None

        if updates_channel_id:
            channel = guild.get_channel(updates_channel_id)
            if isinstance(channel, discord.TextChannel):
                embed = discord.Embed(
                    title="🔄 Core Reboot Activated",
                    description="**The bot is rebooting its core system via the Dashboard.**\nIt should be back online momentarily.",
                    color=discord.Color.from_rgb(255, 165, 0),
                    timestamp=discord.utils.utcnow()
                )
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass

        features = "Dashboard triggered reboot completed."
        await self.db.execute(
            """
            INSERT INTO restart_flags (guild_id, pending, features, channel_id)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET pending = 1, features = excluded.features, channel_id = excluded.channel_id
            """,
            (guild.id, features, updates_channel_id)
        )
        await self.db.execute("UPDATE restart_flags SET channel_id = ? WHERE guild_id = ?", (updates_channel_id, guild.id))
        await self.db.commit()

        log.warning(f"[{guild.name}] Initiating dashboard restart trigger.")
        
        await asyncio.sleep(1.0)
        os.execv(sys.executable, ['python'] + sys.argv)
        return web.json_response({"status": "restarting"})
        
    async def handle_ipc_shutdown(self, request):
        from aiohttp import web
        import asyncio
        import os
        try:
            guild_id = int(request.match_info['guild_id'])
            guild = self.get_guild(guild_id)
            if not guild:
                return web.json_response({"error": "Guild not found"}, status=404)
        except ValueError:
            return web.json_response({"error": "Invalid guild ID"}, status=400)

        cursor = await self.db.execute("SELECT updates_channel_id FROM guild_settings WHERE guild_id = ?", (guild.id,))
        row = await cursor.fetchone()
        
        updates_channel_id = row[0] if row and row[0] else None
        
        if updates_channel_id:
            channel = guild.get_channel(updates_channel_id)
            if isinstance(channel, discord.TextChannel):
                embed = discord.Embed(
                    title="🛠️ System Emergency Shutdown",
                    description="**The bot is going offline via Dashboard signal.**\nManual reboot required.",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass
                
        await self.db.execute(
            """
            INSERT INTO restart_flags (guild_id, pending, features, channel_id)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET pending = 1, features = excluded.features, channel_id = excluded.channel_id
            """,
            (guild.id, "Emergency Dashboard Shutdown Recovery.", updates_channel_id)
        )
        await self.db.execute("UPDATE restart_flags SET channel_id = ? WHERE guild_id = ?", (updates_channel_id, guild.id))
        await self.db.commit()
        
        log.warning(f"[{guild.name}] Initiating dashboard shutdown trigger.")
        await self.close()
        os._exit(0)
        return web.json_response({"status": "shutting_down"})

bot = UltimateBot()

@bot.command(name="sync", help="Manually syncs slash commands to Discord.")
@commands.has_permissions(administrator=True)
async def sync_commands(ctx):
    """
    Manually syncs your slash commands with Discord.
    Usage: !sync
    """
    await ctx.send("⏳ Syncing slash commands with Discord... Please wait.")
    try:
        if GUILD_ID:
            bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
            synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            await ctx.send(f"✅ Successfully synced {len(synced)} slash commands to your guild!")
        else:
            synced = await bot.tree.sync()
            await ctx.send(f"✅ Successfully synced {len(synced)} slash commands globally!")
        log.info(f"[SYNC] Owner manually synced {len(synced)} commands.")
    except Exception as e:
        await ctx.send(f"❌ Failed to sync: {e}")
        log.error(f"[SYNC] Manual sync failed: {e}")

@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    log.info("Guilds I am in:")
    for g in bot.guilds:
        log.info(f"- {g.name} ({g.id})")
        
    if getattr(bot, "db", None):
        try:
            await bot.db.execute("ALTER TABLE restart_flags ADD COLUMN channel_id INTEGER")
        except Exception:
            pass
            
        cursor = await bot.db.execute("SELECT guild_id, features, channel_id FROM restart_flags WHERE pending = 1")
        rows = await cursor.fetchall()
        
        for g_id, features, flag_channel_id in rows:
            guild = bot.get_guild(g_id)
            if guild:
                channel = None
                
                if flag_channel_id:
                    channel = guild.get_channel(flag_channel_id)
                    
                if not channel:
                    c_cursor = await bot.db.execute("SELECT updates_channel_id FROM guild_settings WHERE guild_id = ?", (g_id,))
                    c_row = await c_cursor.fetchone()
                    if c_row and c_row[0]:
                        channel = guild.get_channel(c_row[0])
                        
                if isinstance(channel, discord.TextChannel):
                    embed = discord.Embed(
                        title="🟢 System Online",
                        description=f"**Successfully deployed updates:**\n> {features}",
                        color=discord.Color.brand_green(),
                        timestamp=discord.utils.utcnow()
                    )
                    try:
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        pass
            
            await bot.db.execute("UPDATE restart_flags SET pending = 0 WHERE guild_id = ?", (g_id,))
            
        await bot.db.commit()

if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise SystemExit("ERROR: Set TOKEN in config.py")
    bot.run(TOKEN)
