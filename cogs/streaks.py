# cogs/streaks.py
import discord
import time
from datetime import datetime, timezone, timedelta
from discord.ext import commands
from discord import app_commands


class StreaksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_streak(self, user_id: int, guild_id: int):
        cur = await self.bot.db.execute(
            "SELECT current_streak, best_streak, last_message_date FROM streaks WHERE user_id=? AND guild_id=?",
            (user_id, guild_id)
        )
        row = await cur.fetchone()
        if not row:
            return 0, 0, None
        return row[0], row[1], row[2]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        current, best, last_date = await self.get_streak(message.author.id, message.guild.id)

        if last_date == today:
            return  # Already messaged today

        if last_date:
            last = datetime.strptime(last_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            diff = (now.date() - last.date()).days

            if diff == 1:
                # Streak continues
                current += 1
                best = max(current, best)
            elif diff > 1:
                # Streak broken
                current = 1
        else:
            current = 1
            best = 1

        await self.bot.db.execute(
            """INSERT INTO streaks (user_id, guild_id, current_streak, best_streak, last_message_date) VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET current_streak=?, best_streak=?, last_message_date=?""",
            (message.author.id, message.guild.id, current, best, today, current, best, today)
        )
        await self.bot.db.commit()

        # Bonus reward for streaks (ties into economy)
        if current > 1 and current % 5 == 0:  # Every 5 days
            eco = self.bot.cogs.get("EconomyCog")
            if eco:
                bonus = current * 10
                await eco.add_coins(message.author.id, message.guild.id, bonus)
                try:
                    await message.channel.send(
                        f"🔥 **{message.author.mention}**, you hit a **{current}-day message streak**! Here's **{bonus:,} 🪙** bonus coins!",
                        delete_after=10
                    )
                except discord.Forbidden:
                    pass

    # ---------- /streak ----------

    @app_commands.command(name="streak", description="Check your daily message streak.")
    @app_commands.describe(member="User to check (optional).")
    async def streak(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        current, best, last_date = await self.get_streak(target.id, interaction.guild.id)
        
        embed = discord.Embed(
            title=f"🔥 Streaks — {target.display_name}",
            color=discord.Color.brand_red()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Current Streak", value=f"**{current}** days", inline=True)
        embed.add_field(name="Best Streak", value=f"**{best}** days", inline=True)
        
        if last_date:
            embed.set_footer(text=f"Last message date: {last_date}")
        else:
            embed.set_footer(text="No streak started yet.")
            
        await interaction.response.send_message(embed=embed)

    # ---------- /streak_leaderboard ----------

    @app_commands.command(name="streak_leaderboard", description="View the members with the highest active streaks.")
    async def streak_leaderboard(self, interaction: discord.Interaction):
        cur = await self.bot.db.execute(
            "SELECT user_id, current_streak FROM streaks WHERE guild_id=? ORDER BY current_streak DESC LIMIT 10",
            (interaction.guild.id,)
        )
        rows = await cur.fetchall()
        embed = discord.Embed(title="🔥 Streak Leaderboard", color=discord.Color.brand_red())
        medals = ["🥇", "🥈", "🥉"]
        desc = ""
        for i, (uid, current) in enumerate(rows):
            if current == 0:
                continue
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            m = interaction.guild.get_member(uid)
            name = m.display_name if m else f"User {uid}"
            desc += f"{medal} **{name}** — {current} days\n"
            
        embed.description = desc or "No active streaks yet."
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StreaksCog(bot))
