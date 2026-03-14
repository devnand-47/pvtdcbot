# cogs/birthday.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime
from typing import Optional
from config import ADMIN_ROLE_IDS


def is_admin():
    async def predicate(interaction: discord.Interaction):
        member = interaction.user
        if isinstance(member, discord.Member):
            if member.guild_permissions.administrator:
                return True
            if any(r.id in ADMIN_ROLE_IDS for r in member.roles):
                return True
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        raise app_commands.CheckFailure("Not admin")
    return app_commands.check(predicate)


class BirthdayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_birthdays.start()

    def cog_unload(self):
        self.check_birthdays.cancel()

    # ---------- DB Helpers ----------

    async def get_birthday_channel(self, guild_id: int) -> Optional[int]:
        cur = await self.bot.db.execute(
            "SELECT birthday_channel_id FROM guild_settings WHERE guild_id = ?", (guild_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else None

    # ---------- Background Task ----------

    @tasks.loop(minutes=30)
    async def check_birthdays(self):
        now = datetime.utcnow()
        today_month = now.month
        today_day = now.day
        # Only wish once per day (run at specific hour bracket)
        if now.hour not in (8, 9):
            return
        try:
            cur = await self.bot.db.execute(
                "SELECT user_id, guild_id FROM birthdays WHERE month = ? AND day = ?",
                (today_month, today_day)
            )
            rows = await cur.fetchall()
            for user_id, guild_id in rows:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                member = guild.get_member(user_id)
                if not member:
                    continue
                channel_id = await self.get_birthday_channel(guild_id)
                channel = guild.get_channel(channel_id) if channel_id else None
                if not channel:
                    # Find first writable channel
                    channel = next(
                        (ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages),
                        None
                    )
                if channel:
                    embed = discord.Embed(
                        title="🎂 Happy Birthday!",
                        description=f"Wishing a very happy birthday to {member.mention}! 🎉\nHope your day is incredible! 🎊",
                        color=discord.Color.from_rgb(255, 105, 180),
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text=f"🤖 Agent 47 Birthday System")
                    await channel.send(embed=embed)
        except Exception as e:
            print(f"[Birthday] Error checking birthdays: {e}")

    @check_birthdays.before_loop
    async def before_birthday_check(self):
        await self.bot.wait_until_ready()

    # ---------- /birthday set ----------

    @app_commands.command(name="birthday", description="Set your birthday to receive a wish on your special day!")
    @app_commands.describe(month="Month (1-12)", day="Day (1-31)")
    async def birthday_set(self, interaction: discord.Interaction, month: int, day: int):
        if not (1 <= month <= 12) or not (1 <= day <= 31):
            await interaction.response.send_message("❌ Invalid date. Month: 1-12, Day: 1-31.", ephemeral=True)
            return

        await self.bot.db.execute(
            """
            INSERT INTO birthdays (user_id, guild_id, month, day)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET month = excluded.month, day = excluded.day
            """,
            (interaction.user.id, interaction.guild.id, month, day)
        )
        await self.bot.db.commit()

        await interaction.response.send_message(
            f"🎂 Birthday saved! I'll wish you on **{month}/{day}** every year!", ephemeral=True
        )

    # ---------- /birthday_channel ----------

    @app_commands.command(name="birthday_channel", description="Set the channel for birthday announcements.")
    @is_admin()
    @app_commands.describe(channel="Channel to post birthday wishes in.")
    async def birthday_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.bot.db.execute(
            """
            INSERT INTO guild_settings (guild_id, birthday_channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET birthday_channel_id = excluded.birthday_channel_id
            """,
            (interaction.guild.id, channel.id)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"🎂 Birthday announcements will go to {channel.mention}!", ephemeral=True)

    # ---------- /birthday_remove ----------

    @app_commands.command(name="birthday_remove", description="Remove your saved birthday.")
    async def birthday_remove(self, interaction: discord.Interaction):
        await self.bot.db.execute(
            "DELETE FROM birthdays WHERE user_id = ? AND guild_id = ?",
            (interaction.user.id, interaction.guild.id)
        )
        await self.bot.db.commit()
        await interaction.response.send_message("🗑️ Your birthday has been removed.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BirthdayCog(bot))
