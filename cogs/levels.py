# cogs/levels.py

import discord
from discord.ext import commands
from discord import app_commands
import random
import datetime

try:
    from easy_pil import Editor, load_image_async, Font
    HAS_EASY_PIL = True
except ImportError:
    HAS_EASY_PIL = False

class LevelsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Dictionary to store the last text message time for cooldowns {guild_id: {user_id: timestamp}}
        self.cooldowns = {}

    def get_xp_requirement(self, level: int) -> int:
        """Calculate the XP required to REACH a specific level."""
        return 5 * (level ** 2) + (50 * level) + 100

    async def add_xp(self, user_id: int, guild_id: int, amount: int) -> bool:
        """Returns True if the user leveled up."""
        if not hasattr(self.bot, "db") or not self.bot.db:
            return False

        # Ensure the table exists
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS users_levels (
                user_id INTEGER,
                guild_id INTEGER,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        
        # Check current level/XP
        cursor = await self.bot.db.execute("SELECT xp, level FROM users_levels WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        row = await cursor.fetchone()
        
        if not row:
            xp = amount
            level = 0
            await self.bot.db.execute("INSERT INTO users_levels (user_id, guild_id, xp, level) VALUES (?, ?, ?, ?)", (user_id, guild_id, xp, level))
        else:
            xp = row[0] + amount
            level = row[1]
            await self.bot.db.execute("UPDATE users_levels SET xp = ? WHERE user_id = ? AND guild_id = ?", (xp, user_id, guild_id))

        await self.bot.db.commit()

        # Check for Level Up
        next_level_xp = self.get_xp_requirement(level)
        if xp >= next_level_xp:
            new_level = level + 1
            await self.bot.db.execute("UPDATE users_levels SET level = ? WHERE user_id = ? AND guild_id = ?", (new_level, user_id, guild_id))
            await self.bot.db.commit()
            return True
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Simple 60 second cooldown per user to prevent spamming
        guild_id = message.guild.id
        user_id = message.author.id
        now = datetime.datetime.now(datetime.timezone.utc)

        if guild_id not in self.cooldowns:
            self.cooldowns[guild_id] = {}

        last_time = self.cooldowns[guild_id].get(user_id)
        if last_time and (now - last_time).total_seconds() < 60:
            return

        # Give them random XP between 15 and 25
        xp_gain = random.randint(15, 25)
        self.cooldowns[guild_id][user_id] = now
        
        leveled_up = await self.add_xp(user_id, guild_id, xp_gain)

        if leveled_up:
            # Check if there's a specialized level up channel config (optional) or just reply in the same channel
            cursor = await self.bot.db.execute("SELECT level FROM users_levels WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
            row = await cursor.fetchone()
            new_lvl = row[0] if row else 0
            
            try:
                await message.channel.send(f"🎉 Congrats {message.author.mention}, you just leveled up to **Level {new_lvl}**!")
            except discord.Forbidden:
                pass


    @app_commands.command(name="rank", description="Check your or another user's level and rank globally.")
    async def rank_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        if target.bot:
            await interaction.response.send_message("❌ Bots don't have ranks!", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        if getattr(self.bot, "db", None) is None:
            await interaction.followup.send("❌ Database unavailable.")
            return

        # Ensure the table exists
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS users_levels (
                user_id INTEGER,
                guild_id INTEGER,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await self.bot.db.commit()

        cursor = await self.bot.db.execute("SELECT xp, level FROM users_levels WHERE user_id = ? AND guild_id = ?", (target.id, interaction.guild.id))
        row = await cursor.fetchone()

        if not row:
            await interaction.followup.send(f"❌ **{target.display_name}** hasn't sent any messages yet!")
            return

        xp = row[0]
        level = row[1]
        
        # Calculate rank globally in the server
        rank_cursor = await self.bot.db.execute("SELECT COUNT(*) FROM users_levels WHERE guild_id = ? AND xp > ?", (interaction.guild.id, xp))
        rank_row = await rank_cursor.fetchone()
        rank = rank_row[0] + 1

        next_level_xp = self.get_xp_requirement(level)
        prev_level_xp = self.get_xp_requirement(level - 1) if level > 0 else 0
        
        current_layer_xp = xp - prev_level_xp
        required_layer_xp = next_level_xp - prev_level_xp
        percentage = int((current_layer_xp / required_layer_xp) * 100) if required_layer_xp > 0 else 100

        if HAS_EASY_PIL:
            # Generate a beautiful image card!
            background = Editor("https://w0.peakpx.com/wallpaper/726/468/HD-wallpaper-neon-geometric-shapes-dark-background-art.jpg") # Fallback neat background
            profile_image = await load_image_async(str(target.display_avatar.url))

            profile = Editor(profile_image).resize((150, 150)).circle_image()
            
            # Use default fonts for cross-platform compatibility
            poppins = Font.poppins(size=40)
            poppins_small = Font.poppins(size=30)

            background.paste(profile, (30, 30))
            background.text((200, 40), str(target.name), font=poppins, color="white")
            
            background.text((200, 90), f"Level: {level}", font=poppins_small, color="white")
            background.text((450, 90), f"Rank: #{rank}", font=poppins_small, color="white")
            
            background.rectangle((200, 130), width=350, height=20, outline="white", stroke_width=2, radius=10)
            
            progress_width = int(350 * (percentage / 100))
            if progress_width > 0:
                background.rectangle((200, 130), width=progress_width, height=20, fill="#00ff99", radius=10)
                
            background.text((200, 160), f"{current_layer_xp} / {required_layer_xp} XP", font=poppins_small, color="white")

            file = discord.File(fp=background.image_bytes, filename="rank.png")
            await interaction.followup.send(file=file)
        else:
            # Fallback embed if library failed to load
            embed = discord.Embed(title=f"🔰 {target.display_name}'s Rank", color=discord.Color.blurple())
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(name="Level", value=str(level), inline=True)
            embed.add_field(name="Rank", value=f"#{rank}", inline=True)
            embed.add_field(name="XP Progress", value=f"{current_layer_xp} / {required_layer_xp} XP ({percentage}%)", inline=False)
            
            # ASCII Bar
            bar = "█" * int(percentage / 10) + "░" * (10 - int(percentage / 10))
            embed.add_field(name="Progress Bar", value=f"`{bar}`", inline=False)
            
            await interaction.followup.send(embed=embed)


    @app_commands.command(name="leaderboard", description="View the Top 10 users in this server!")
    async def leaderboard_slash(self, interaction: discord.Interaction):
        if getattr(self.bot, "db", None) is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        # Ensure the table exists
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS users_levels (
                user_id INTEGER,
                guild_id INTEGER,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await self.bot.db.commit()

        cursor = await self.bot.db.execute("SELECT user_id, xp, level FROM users_levels WHERE guild_id = ? ORDER BY xp DESC LIMIT 10", (interaction.guild.id,))
        rows = await cursor.fetchall()

        if not rows:
            await interaction.response.send_message("❌ No one has earned any XP yet!", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 Server Leaderboard",
            color=discord.Color.gold()
        )
        
        desc = ""
        for i, row in enumerate(rows):
            target_id, xp, level = row
            target = interaction.guild.get_member(target_id)
            name = target.display_name if target else f"Unknown User ({target_id})"
            
            medal = "🏅"
            if i == 0: medal = "🥇"
            elif i == 1: medal = "🥈"
            elif i == 2: medal = "🥉"
            
            desc += f"**{i+1}.** {medal} **{name}** - `Level {level}` ({xp} XP)\n"
            
        embed.description = desc
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(LevelsCog(bot))
