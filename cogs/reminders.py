# cogs/reminders.py
import time
import asyncio
import re
import discord
from discord.ext import commands, tasks
from discord import app_commands


def parse_seconds(raw: str) -> int | None:
    m = re.fullmatch(r"(\d+)([smhd])", raw.strip().lower())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    return val * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


class RemindersCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    @tasks.loop(seconds=15)
    async def check_reminders(self):
        if not self.bot.db:
            return
        now = int(time.time())
        cur = await self.bot.db.execute(
            "SELECT id, user_id, channel_id, message FROM reminders WHERE remind_at <= ? AND done = 0",
            (now,)
        )
        rows = await cur.fetchall()
        for rid, user_id, channel_id, message in rows:
            try:
                user = await self.bot.fetch_user(user_id)
                channel = self.bot.get_channel(channel_id)
                target = channel or user  # DM fallback
                embed = discord.Embed(
                    title="⏰ Reminder!",
                    description=message,
                    color=discord.Color.blurple()
                )
                embed.set_footer(text="This was your scheduled reminder.")
                await target.send(content=user.mention if channel else None, embed=embed)
            except Exception as e:
                print(f"[Reminders] Failed to send reminder {rid}: {e}")
            await self.bot.db.execute("UPDATE reminders SET done = 1 WHERE id = ?", (rid,))
        if rows:
            await self.bot.db.commit()

    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ---------- /remind ----------

    @app_commands.command(name="remind", description="Set a personal reminder.")
    @app_commands.describe(duration="When to remind you: 10m, 2h, 1d.", message="What to remind you about.")
    async def remind(self, interaction: discord.Interaction, duration: str, message: str):
        seconds = parse_seconds(duration)
        if not seconds or seconds < 5:
            await interaction.response.send_message("❌ Invalid duration. Use `30s`, `10m`, `2h`, `1d`.", ephemeral=True)
            return

        remind_at = int(time.time()) + seconds
        await self.bot.db.execute(
            "INSERT INTO reminders (user_id, channel_id, message, remind_at, done) VALUES (?,?,?,?,0)",
            (interaction.user.id, interaction.channel_id, message, remind_at)
        )
        await self.bot.db.commit()

        await interaction.response.send_message(
            f"⏰ Got it! I'll remind you **<t:{remind_at}:R>** about:\n> {message}",
            ephemeral=True
        )

    # ---------- /reminders ----------

    @app_commands.command(name="reminders", description="View your pending reminders.")
    async def reminders_list(self, interaction: discord.Interaction):
        cur = await self.bot.db.execute(
            "SELECT id, message, remind_at FROM reminders WHERE user_id=? AND done=0 ORDER BY remind_at",
            (interaction.user.id,)
        )
        rows = await cur.fetchall()
        embed = discord.Embed(title="⏰ Your Reminders", color=discord.Color.blurple())
        if not rows:
            embed.description = "You have no pending reminders."
        else:
            for rid, msg, rat in rows:
                embed.add_field(name=f"ID `{rid}` — <t:{rat}:R>", value=msg[:80], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------- /reminder_cancel ----------

    @app_commands.command(name="reminder_cancel", description="Cancel a scheduled reminder by ID.")
    @app_commands.describe(reminder_id="ID of the reminder to cancel.")
    async def reminder_cancel(self, interaction: discord.Interaction, reminder_id: int):
        await self.bot.db.execute(
            "UPDATE reminders SET done=1 WHERE id=? AND user_id=?",
            (reminder_id, interaction.user.id)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Reminder `#{reminder_id}` cancelled.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RemindersCog(bot))
