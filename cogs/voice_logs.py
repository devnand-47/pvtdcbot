# cogs/voice_logs.py

import discord
from discord.ext import commands
from discord import app_commands
import datetime
import sqlite3

class VoiceLogsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _fetch_log_channel(self, guild_id: int):
        if not hasattr(self.bot, "db") or not self.bot.db:
            return None

        try:
            cursor = await self.bot.db.execute(
                "SELECT voice_log_channel_id FROM guild_settings WHERE guild_id = ?",
                (guild_id,)
            )
            row = await cursor.fetchone()
            if row and row[0]:
                return row[0]
        except Exception:
            pass
        return None

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        if not hasattr(self.bot, "db") or not self.bot.db:
            return

        guild_id = member.guild.id
        now = datetime.datetime.now(datetime.timezone.utc)

        try:
            # Ensure table exists
            await self.bot.db.execute("""
                CREATE TABLE IF NOT EXISTS voice_sessions (
                    user_id INTEGER,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    join_time TIMESTAMP,
                    video_start TIMESTAMP,
                    video_total REAL DEFAULT 0.0,
                    stream_start TIMESTAMP,
                    stream_total REAL DEFAULT 0.0,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            await self.bot.db.commit()

            # Session End (Disconnecting completely OR moving to another channel)
            if before.channel is not None and (after.channel is None or before.channel.id != after.channel.id):
                reason = "Left the channel"
                if after.channel is not None:
                    reason = f"Moved to <#{after.channel.id}>"

                # Check audit logs for Admin Actions
                if member.guild.me.guild_permissions.view_audit_log:
                    try:
                        if after.channel is None:
                            async for entry in member.guild.audit_logs(limit=3, action=discord.AuditLogAction.member_disconnect):
                                if getattr(entry.target, 'id', None) == member.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                                    reason = f"Disconnected by {entry.user.mention}"
                                    break
                        else:
                            async for entry in member.guild.audit_logs(limit=3, action=discord.AuditLogAction.member_move):
                                if getattr(entry.target, 'id', None) == member.id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                                    reason = f"Moved by {entry.user.mention} to <#{after.channel.id}>"
                                    break
                    except discord.Forbidden:
                        pass

                # Fetch and delete old session
                cursor = await self.bot.db.execute("SELECT channel_id, join_time, video_start, video_total, stream_start, stream_total FROM voice_sessions WHERE user_id = ? AND guild_id = ?", (member.id, guild_id))
                row = await cursor.fetchone()
                if row:
                    channel_id, join_time, video_start, video_total, stream_start, stream_total = row
                    
                    start_dt = datetime.datetime.fromisoformat(join_time)
                    session_duration = (now - start_dt).total_seconds()

                    if video_start:
                        v_start_dt = datetime.datetime.fromisoformat(video_start)
                        video_total += (now - v_start_dt).total_seconds()
                    
                    if stream_start:
                        s_start_dt = datetime.datetime.fromisoformat(stream_start)
                        stream_total += (now - s_start_dt).total_seconds()

                    await self.bot.db.execute("DELETE FROM voice_sessions WHERE user_id = ? AND guild_id = ?", (member.id, guild_id))
                    
                    # Accumulate in voice_stats
                    await self.bot.db.execute(
                        """
                        INSERT INTO voice_stats (user_id, guild_id, total_seconds)
                        VALUES (?, ?, ?)
                        ON CONFLICT(user_id, guild_id) DO UPDATE SET
                            total_seconds = total_seconds + excluded.total_seconds
                        """,
                        (member.id, guild_id, session_duration)
                    )
                    
                    await self.bot.db.commit()

                    # Send Report
                    log_chan_id = await self._fetch_log_channel(guild_id)
                    if log_chan_id:
                        log_channel = self.bot.get_channel(log_chan_id)
                        if log_channel:
                            def format_duration(seconds: float) -> str:
                                m, s = divmod(int(seconds), 60)
                                h, m = divmod(m, 60)
                                if h > 0:
                                    return f"{h}h {m}m {s}s"
                                elif m > 0:
                                    return f"{m}m {s}s"
                                else:
                                    return f"{s}s"

                            embed = discord.Embed(
                                title="🎙️ Voice Activity Report",
                                color=discord.Color.blurple() if after.channel is None else discord.Color.orange(),
                                timestamp=now
                            )
                            embed.set_author(name=f"{member.display_name} ({member.id})", icon_url=member.display_avatar.url if member.display_avatar else None)
                            embed.add_field(name="Channel", value=f"<#{channel_id}>", inline=False)
                            embed.add_field(name="Connected", value=discord.utils.format_dt(start_dt, style="T"), inline=True)
                            if after.channel is None:
                                embed.add_field(name="Disconnected", value=discord.utils.format_dt(now, style="T"), inline=True)
                            else:
                                embed.add_field(name="Switched", value=discord.utils.format_dt(now, style="T"), inline=True)
                            embed.add_field(name="Total Duration", value=f"⏳ {format_duration(session_duration)}", inline=True)
                            if video_total > 0:
                                embed.add_field(name="Camera Used", value=f"📷 {format_duration(video_total)}", inline=True)
                            if stream_total > 0:
                                embed.add_field(name="Screen Shared", value=f"💻 {format_duration(stream_total)}", inline=True)
                            embed.add_field(name="Reason", value=reason, inline=False)
                            
                            await log_channel.send(embed=embed)

            # Session Start (Joining a channel completely OR moving into a new channel)
            if after.channel is not None and (before.channel is None or before.channel.id != after.channel.id):
                v_start = now.isoformat() if after.self_video else None
                s_start = now.isoformat() if after.self_stream else None

                await self.bot.db.execute(
                    """
                    INSERT INTO voice_sessions (user_id, guild_id, channel_id, join_time, video_start, video_total, stream_start, stream_total)
                    VALUES (?, ?, ?, ?, ?, 0.0, ?, 0.0)
                    ON CONFLICT(user_id, guild_id) DO UPDATE SET
                        channel_id = excluded.channel_id,
                        join_time = excluded.join_time,
                        video_start = excluded.video_start,
                        video_total = 0.0,
                        stream_start = excluded.stream_start,
                        stream_total = 0.0
                    """,
                    (member.id, guild_id, after.channel.id, now.isoformat(), v_start, s_start)
                )
                await self.bot.db.commit()

            # State change while IN the SAME channel
            elif before.channel is not None and after.channel is not None and before.channel.id == after.channel.id:
                cursor = await self.bot.db.execute("SELECT video_start, video_total, stream_start, stream_total FROM voice_sessions WHERE user_id = ? AND guild_id = ?", (member.id, guild_id))
                row = await cursor.fetchone()
                if not row:
                    return

                video_start, video_total, stream_start, stream_total = row

                # Video Camera toggled
                if not before.self_video and after.self_video:
                    await self.bot.db.execute("UPDATE voice_sessions SET video_start = ? WHERE user_id = ? AND guild_id = ?", (now.isoformat(), member.id, guild_id))
                elif before.self_video and not after.self_video and video_start:
                    start_dt = datetime.datetime.fromisoformat(video_start)
                    duration = (now - start_dt).total_seconds()
                    await self.bot.db.execute("UPDATE voice_sessions SET video_total = video_total + ?, video_start = NULL WHERE user_id = ? AND guild_id = ?", (duration, member.id, guild_id))

                # Screen Share toggled
                if not before.self_stream and after.self_stream:
                    await self.bot.db.execute("UPDATE voice_sessions SET stream_start = ? WHERE user_id = ? AND guild_id = ?", (now.isoformat(), member.id, guild_id))
                elif before.self_stream and not after.self_stream and stream_start:
                    start_dt = datetime.datetime.fromisoformat(stream_start)
                    duration = (now - start_dt).total_seconds()
                    await self.bot.db.execute("UPDATE voice_sessions SET stream_total = stream_total + ?, stream_start = NULL WHERE user_id = ? AND guild_id = ?", (duration, member.id, guild_id))

                await self.bot.db.commit()

        except Exception as e:
            print(f"Voice Log Error: {e}")

    @app_commands.command(name="voice", description="Check how long a user has been in a voice channel.")
    async def voice_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        await self._handle_voice_query(interaction, target)

    @commands.command(name="voice")
    async def voice_command(self, ctx: commands.Context, member: discord.Member = None):
        target = member or ctx.author
        await self._handle_voice_query(ctx, target)

    async def _handle_voice_query(self, ctx_or_int, member: discord.Member):
        if not hasattr(self.bot, "db") or not self.bot.db:
            return

        respond = ctx_or_int.response.send_message if isinstance(ctx_or_int, discord.Interaction) else ctx_or_int.send

        # If they aren't even connected right now
        if member.voice is None or member.voice.channel is None:
            await respond(f"❌ **{member.display_name}** is not currently in any Voice Channel.")
            return

        cursor = await self.bot.db.execute("SELECT channel_id, join_time, video_start, video_total, stream_start, stream_total FROM voice_sessions WHERE user_id = ? AND guild_id = ?", (member.id, member.guild.id))
        row = await cursor.fetchone()
        
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # They are in a VC, but the bot missed the `on_voice_state_update` (perhaps it rebooted)
        if not row:
            v_start = now.isoformat() if member.voice.self_video else None
            s_start = now.isoformat() if member.voice.self_stream else None
            
            # Seed the database and start tracking them now
            await self.bot.db.execute(
                """
                INSERT INTO voice_sessions (user_id, guild_id, channel_id, join_time, video_start, video_total, stream_start, stream_total)
                VALUES (?, ?, ?, ?, ?, 0.0, ?, 0.0)
                """,
                (member.id, member.guild.id, member.voice.channel.id, now.isoformat(), v_start, s_start)
            )
            await self.bot.db.commit()
            
            # Simulated variables for the embed since they just started tracking
            channel_id = member.voice.channel.id
            join_time = now.isoformat()
            video_start = v_start
            video_total = 0.0
            stream_start = s_start
            stream_total = 0.0
        else:
            channel_id, join_time, video_start, video_total, stream_start, stream_total = row

        start_dt = datetime.datetime.fromisoformat(join_time)
        session_duration = (now - start_dt).total_seconds()

        if video_start:
            v_start_dt = datetime.datetime.fromisoformat(video_start)
            video_total += (now - v_start_dt).total_seconds()
        
        if stream_start:
            s_start_dt = datetime.datetime.fromisoformat(stream_start)
            stream_total += (now - s_start_dt).total_seconds()

        def format_duration(seconds: float) -> str:
            if seconds < 1:
                return "Just joined"
            m, s = divmod(int(seconds), 60)
            h, m = divmod(m, 60)
            if h > 0:
                return f"{h}h {m}m {s}s"
            elif m > 0:
                return f"{m}m {s}s"
            else:
                return f"{s}s"

        embed = discord.Embed(
            title="🗣️ Active Voice Session",
            color=discord.Color.green(),
            timestamp=now
        )
        embed.set_author(name=f"{member.display_name} ({member.id})", icon_url=member.display_avatar.url if member.display_avatar else None)
        embed.add_field(name="Channel", value=f"<#{channel_id}>", inline=False)
        embed.add_field(name="Tracking Started", value=discord.utils.format_dt(start_dt, style="R"), inline=True)
        embed.add_field(name="Current Duration", value=f"⏳ {format_duration(session_duration)}", inline=True)
        
        if video_total > 0:
            embed.add_field(name="Camera Used", value=f"📷 {format_duration(video_total)}", inline=True)
        if stream_total > 0:
            embed.add_field(name="Screen Shared", value=f"💻 {format_duration(stream_total)}", inline=True)
        
        await respond(embed=embed)

    @app_commands.command(name="voiceleaderboard", description="View the top users with the most voice time!")
    async def voiceleaderboard_slash(self, interaction: discord.Interaction):
        if not hasattr(self.bot, "db") or not self.bot.db:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return
            
        # Ensure the table exists in case bot hasn't restarted yet
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS voice_stats (
                user_id INTEGER,
                guild_id INTEGER,
                total_seconds REAL DEFAULT 0.0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await self.bot.db.commit()

        cursor = await self.bot.db.execute("SELECT user_id, total_seconds FROM voice_stats WHERE guild_id = ? ORDER BY total_seconds DESC LIMIT 10", (interaction.guild.id,))
        rows = await cursor.fetchall()
        
        if not rows:
            await interaction.response.send_message("❌ No one has spent time in voice channels yet!", ephemeral=True)
            return

        embed = discord.Embed(
            title="🗣️ Server Voice Leaderboard",
            color=discord.Color.gold()
        )
        
        def format_duration(seconds: float) -> str:
            m, s = divmod(int(seconds), 60)
            h, m = divmod(m, 60)
            if h > 0:
                return f"{h}h {m}m"
            elif m > 0:
                return f"{m}m {s}s"
            else:
                return f"{s}s"
        
        desc = ""
        for i, row in enumerate(rows):
            target_id, total_seconds = row
            target = interaction.guild.get_member(target_id)
            name = target.display_name if target else f"Unknown User ({target_id})"
            
            medal = "🏅"
            if i == 0: medal = "🥇"
            elif i == 1: medal = "🥈"
            elif i == 2: medal = "🥉"
            
            desc += f"**{i+1}.** {medal} **{name}** - `{format_duration(total_seconds)}`\n"
            
        embed.description = desc
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceLogsCog(bot))
