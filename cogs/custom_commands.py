# cogs/custom_commands.py

import discord
from discord.ext import commands

class CustomCommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Use an absolute prefix that the dynamic commands respond to, or listen to all text.
        # Let's listen to all text and see if it perfectly equals a defined custom command trigger.
        content = message.content.strip()
        
        if not hasattr(self.bot, "db") or not self.bot.db:
            return

        # Ensure the table exists
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS custom_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                trigger TEXT,
                response_content TEXT
            )
        """)
        await self.bot.db.commit()

        # Query the database
        cursor = await self.bot.db.execute(
            "SELECT response_content FROM custom_commands WHERE guild_id = ? AND trigger = ? COLLATE NOCASE", 
            (message.guild.id, content)
        )
        row = await cursor.fetchone()

        if row:
            response_content = row[0]
            try:
                await message.channel.send(response_content)
            except discord.Forbidden:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomCommandsCog(bot))
