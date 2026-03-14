# cogs/admin.py

import time
from typing import Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands

from config import (
    ADMIN_ROLE_IDS,
    LOG_CHANNEL_ID,
)


def is_admin():
    async def predicate(interaction: discord.Interaction):
        member = interaction.user
        if isinstance(member, discord.Member):
            if member.guild_permissions.administrator:
                return True
            if any(r.id in ADMIN_ROLE_IDS for r in member.roles):
                return True

        await interaction.response.send_message(
            "❌ You must be an administrator / staff to use this command.",
            ephemeral=True,
        )
        raise app_commands.CheckFailure("Not admin")

    return app_commands.check(predicate)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_scheduled_announcements.start()

    def cog_unload(self):
        self.check_scheduled_announcements.cancel()

    # ---------- internal: moderation log ----------

    async def log_action(
        self,
        guild: discord.Guild,
        actor: discord.abc.User,
        user: Optional[discord.abc.User],
        action: str,
        reason: str = "",
    ):
        if self.bot.db is None:
            return

        user_id = user.id if user else 0
        actor_id = actor.id
        now = int(time.time())

        await self.bot.db.execute(
            """
            INSERT INTO moderation_logs (guild_id, user_id, actor_id, action, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild.id, user_id, actor_id, action, reason, now),
        )
        await self.bot.db.commit()

        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            embed = discord.Embed(
                title="🔍 Moderation Log",
                description=f"**Action:** {action}",
                color=discord.Color.orange(),
            )
            if user:
                embed.add_field(
                    name="Target", value=f"{user} ({user.id})", inline=False
                )
            embed.add_field(
                name="Actor", value=f"{actor} ({actor.id})", inline=False
            )
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)
            embed.timestamp = discord.utils.utcnow()
            await log_channel.send(embed=embed)

    # ---------- /say ----------

    @app_commands.command(
        name="say",
        description="Send a message to a channel as the bot.",
    )
    @is_admin()
    @app_commands.describe(
        message="The message. You can use Discord markdown.",
        channel="Channel to send in (optional, defaults to current).",
    )
    async def say(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: Optional[discord.TextChannel] = None,
    ):
        target_channel = channel or interaction.channel
        
        if not isinstance(target_channel, discord.TextChannel) and not isinstance(target_channel, discord.Thread):
            await interaction.response.send_message("❌ Invalid channel type.", ephemeral=True)
            return

        try:
            await target_channel.send(message)
            await interaction.response.send_message(
                f"✅ Message successfully sent to {target_channel.mention}", 
                ephemeral=True
            )
            
            # Optionally log the action
            if interaction.guild:
                await self.log_action(
                    guild=interaction.guild,
                    actor=interaction.user,
                    user=None,
                    action="say",
                    reason=f"Sent a message in {target_channel.mention}",
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ **Error:** I lack the permissions to send messages in that channel.", 
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ **Error:** {e}", ephemeral=True)

    # ---------- /poll ----------

    @app_commands.command(name="poll", description="Create a poll with up to 4 options.")
    @is_admin()
    @app_commands.describe(
        question="The poll question.",
        option1="First option.",
        option2="Second option.",
        option3="Third option (optional).",
        option4="Fourth option (optional).",
        channel="Channel to post in (optional).",
    )
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: Optional[str] = None,
        option4: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None,
    ):
        target = channel or interaction.channel
        emojis = ["🇦", "🇧", "🇨", "🇩"]
        options = [o for o in [option1, option2, option3, option4] if o]

        description = "\n".join([f"{emojis[i]} **{opt}**" for i, opt in enumerate(options)])
        embed = discord.Embed(
            title=f"📊 {question}",
            description=description,
            color=discord.Color.from_rgb(88, 101, 242),
        )
        embed.set_footer(text=f"Poll by {interaction.user.display_name} • React to vote!")

        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("❌ Invalid channel.", ephemeral=True)
            return

        msg = await target.send(embed=embed)
        for i in range(len(options)):
            await msg.add_reaction(emojis[i])

        await interaction.response.send_message(f"✅ Poll posted in {target.mention}!", ephemeral=True)

    # ---------- /announce ----------

    @app_commands.command(
        name="announce",
        description="Send a cyber-style announcement.",
    )
    @is_admin()
    @app_commands.describe(
        message="Text of the announcement.",
        channel="Channel to send in (optional).",
    )
    async def announce(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: Optional[discord.TextChannel] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Guild not found.", ephemeral=True
            )
            return

        if channel is None:
            # if you want, you can read default channel from DB here
            channel = interaction.channel  # type: ignore

        if channel is None:
            await interaction.response.send_message(
                "❌ I couldn't find a channel to send the announcement.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="⚠ Network-Wide Broadcast",
            description=message,
            color=discord.Color.from_rgb(0, 255, 255),
        )
        embed.set_footer(text=f"Transmission by {interaction.user.display_name}")

        await channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Announcement sent in {channel.mention}.",
            ephemeral=True,
        )

        await self.log_action(
            guild=guild,
            actor=interaction.user,
            user=None,
            action="announce",
            reason=f"Channel: #{channel.name}",
        )

    # ---------- /maintenance ----------

    @app_commands.command(
        name="maintenance",
        description="Shut down the bot for an update and set a restart flag.",
    )
    @is_admin()
    @app_commands.describe(
        message="Features added or maintenance reason.",
        channel="Optional channel to send the reboot signal to.",
    )
    async def maintenance(self, interaction: discord.Interaction, message: str, channel: Optional[discord.TextChannel] = None):
        guild = interaction.guild
        if guild is None or self.bot.db is None:
            await interaction.response.send_message("❌ Database error.", ephemeral=True)
            return
            
        # Get the update channel
        updates_channel_id = None
        if not channel:
            cursor = await self.bot.db.execute("SELECT updates_channel_id FROM guild_settings WHERE guild_id = ?", (guild.id,))
            row = await cursor.fetchone()
            updates_channel_id = row[0] if row and row[0] else None
            if updates_channel_id:
                channel = guild.get_channel(updates_channel_id)
            
        if channel and isinstance(channel, discord.TextChannel):
            embed = discord.Embed(
                title="🛠️ System Maintenance",
                description=f"**The bot is going offline for an update:**\n> {message}",
                color=discord.Color.gold(),
                timestamp=discord.utils.utcnow()
            )
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                pass
                
        # Set the restart flag so it announces when it boots back up
        target_channel_id = channel.id if channel else None
        await self.bot.db.execute(
            """
            INSERT INTO restart_flags (guild_id, pending, features, channel_id)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET pending = 1, features = excluded.features, channel_id = excluded.channel_id
            """,
            (guild.id, message, target_channel_id)
        )
        if target_channel_id:
            await self.bot.db.execute("UPDATE restart_flags SET channel_id = ? WHERE guild_id = ?", (target_channel_id, guild.id))
        await self.bot.db.commit()
        
        await interaction.response.send_message(f"✅ Maintenance mode armed. Shutting down system now.", ephemeral=True)
        print(f"[{guild.name}] Initiating maintenance shutdown trigger by {interaction.user}.")
        await self.bot.close()

    # ---------- scheduled announcements ----------

    @app_commands.command(
        name="schedule_announce",
        description="Schedule an announcement for later.",
    )
    @is_admin()
    @app_commands.describe(
        message="Text of the announcement.",
        delay_minutes="Delay before sending (in minutes).",
        channel="Channel to send in (optional).",
    )
    async def schedule_announce(
        self,
        interaction: discord.Interaction,
        message: str,
        delay_minutes: app_commands.Range[int, 1, 60 * 24],
        channel: Optional[discord.TextChannel] = None,
    ):
        guild = interaction.guild
        if guild is None or self.bot.db is None:
            await interaction.response.send_message(
                "❌ Scheduling failed (no guild/db).", ephemeral=True
            )
            return

        if channel is None:
            channel = interaction.channel  # type: ignore

        if channel is None:
            await interaction.response.send_message(
                "❌ I couldn't find a channel to schedule in.",
                ephemeral=True,
            )
            return

        run_at = int(time.time()) + delay_minutes * 60

        await self.bot.db.execute(
            """
            INSERT INTO scheduled_announcements (guild_id, channel_id, message, run_at)
            VALUES (?, ?, ?, ?)
            """,
            (guild.id, channel.id, message, run_at),
        )
        await self.bot.db.commit()

        await interaction.response.send_message(
            f"✅ Scheduled announcement in {channel.mention} in {delay_minutes} minute(s).",
            ephemeral=True,
        )

        await self.log_action(
            guild=guild,
            actor=interaction.user,
            user=None,
            action="schedule_announce",
            reason=f"Channel: #{channel.name}, delay={delay_minutes}m",
        )

    @tasks.loop(seconds=5)
    async def check_scheduled_announcements(self):
        if self.bot.db is None:
            return

        now = int(time.time())
        cursor = await self.bot.db.execute(
            """
            SELECT id, guild_id, channel_id, message, title, color
            FROM scheduled_announcements
            WHERE sent = 0 AND (run_at <= ? OR instant = 1)
            """,
            (now,),
        )
        rows = await cursor.fetchall()

        for ann_id, guild_id, channel_id, message, title, hex_color in rows:
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
                
            try:
                emb_color = discord.Color(int((hex_color or "#00FFFF").replace("#", ""), 16))
            except ValueError:
                emb_color = discord.Color.blue()

            # Professional Broadcast Formatting
            embed = discord.Embed(
                title=title or "📡 Scheduled Transmission",
                description=f"> {message}\n\n",
                color=emb_color,
                timestamp=discord.utils.utcnow()
            )
            
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)
                
            embed.set_author(name=f"{guild.name} Official Broadcast", icon_url=guild.icon.url if guild.icon else None)
            embed.set_footer(text="Automated Server Announcement System")
            
            await channel.send(embed=embed)

            await self.bot.db.execute(
                "UPDATE scheduled_announcements SET sent = 1 WHERE id = ?",
                (ann_id,),
            )
        await self.bot.db.commit()

    @check_scheduled_announcements.before_loop
    async def before_check_scheduled_announcements(self):
        await self.bot.wait_until_ready()

    # ---------- /clear ----------

    @app_commands.command(
        name="clear",
        description="Clear messages in a channel (admin only).",
    )
    @is_admin()
    @app_commands.describe(
        amount="How many messages to delete (1–200).",
        channel="Channel to clear (default: current).",
    )
    async def clear(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 200],
        channel: Optional[discord.TextChannel] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Guild not found.", ephemeral=True
            )
            return

        target_channel = channel or interaction.channel  # type: ignore
        deleted = await target_channel.purge(limit=amount + 1)
        count = max(len(deleted) - 1, 0)

        await interaction.response.send_message(
            f"🧹 Cleared `{count}` messages in {target_channel.mention}.",
            ephemeral=True,
        )

        await self.log_action(
            guild=guild,
            actor=interaction.user,
            user=None,
            action="clear",
            reason=f"{count} messages in #{target_channel.name}",
        )

    # ---------- /slowmode ----------

    @app_commands.command(
        name="slowmode",
        description="Set slowmode on a channel (admin only).",
    )
    @is_admin()
    @app_commands.describe(
        seconds="Slowmode delay in seconds (0 to disable).",
        channel="Channel to apply to (default: current).",
    )
    async def slowmode(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, 21600],
        channel: Optional[discord.TextChannel] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Guild not found.", ephemeral=True
            )
            return

        target_channel = channel or interaction.channel  # type: ignore
        await target_channel.edit(slowmode_delay=seconds)

        msg = (
            f"🐢 Enabled slowmode `{seconds}`s in {target_channel.mention}."
            if seconds > 0
            else f"🚀 Disabled slowmode in {target_channel.mention}."
        )

        await interaction.response.send_message(msg, ephemeral=True)

        await self.log_action(
            guild=guild,
            actor=interaction.user,
            user=None,
            action="slowmode",
            reason=f"{seconds}s in #{target_channel.name}",
        )

    # ---------- /lockdown ----------

    @app_commands.command(
        name="lockdown",
        description="Lock or unlock a channel (admin only).",
    )
    @is_admin()
    @app_commands.describe(
        locked="True = lock channel, False = unlock.",
        channel="Channel to lock/unlock (default: current).",
    )
    async def lockdown(
        self,
        interaction: discord.Interaction,
        locked: bool,
        channel: Optional[discord.TextChannel] = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Guild not found.", ephemeral=True
            )
            return

        target_channel = channel or interaction.channel  # type: ignore
        overwrite = target_channel.overwrites_for(guild.default_role)
        overwrite.send_messages = None if not locked else False
        await target_channel.set_permissions(guild.default_role, overwrite=overwrite)

        status = "🔒 Channel locked." if locked else "🔓 Channel unlocked."
        await interaction.response.send_message(
            f"{status} {target_channel.mention}", ephemeral=True
        )

        await self.log_action(
            guild=guild,
            actor=interaction.user,
            user=None,
            action="lockdown",
            reason=f"{'locked' if locked else 'unlocked'} #{target_channel.name}",
        )

    # ---------- /logs ----------

    @app_commands.command(
        name="logs",
        description="View last moderation logs.",
    )
    @is_admin()
    @app_commands.describe(
        limit="How many entries to show (1–50).",
    )
    async def logs(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 50] = 10,
    ):
        guild = interaction.guild
        if guild is None or self.bot.db is None:
            await interaction.response.send_message(
                "❌ Cannot fetch logs.", ephemeral=True
            )
            return

        cur = await self.bot.db.execute(
            """
            SELECT user_id, actor_id, action, reason, created_at
            FROM moderation_logs
            WHERE guild_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (guild.id, limit),
        )
        rows = await cur.fetchall()

        if not rows:
            await interaction.response.send_message(
                "ℹ No moderation logs yet.", ephemeral=True
            )
            return

        lines = []
        for user_id, actor_id, action, reason, created_at in rows:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at))
            user_txt = f"{user_id}" if user_id else "-"
            reason_txt = reason or "-"
            lines.append(
                f"[{ts}] action={action}, target={user_txt}, by={actor_id}, reason={reason_txt}"
            )

        text = "```" + "\n".join(lines) + "```"
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
