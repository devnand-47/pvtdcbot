# cogs/fun.py

import random

import discord
from discord.ext import commands

MEMES = [
    "https://i.imgflip.com/30b1gx.jpg",
    "https://i.imgflip.com/1bij.jpg",
    "https://i.imgflip.com/26am.jpg",
]

EIGHTBALL = [
    "Yes.",
    "No.",
    "Maybe.",
    "Ask again later.",
    "Definitely.",
    "I doubt it.",
]


class FunCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context):
        import time
        
        # 1. Measure REST API latency (time taken to send a message)
        start_time = time.perf_counter()
        message = await ctx.send("📡 Pinging clusters...")
        end_time = time.perf_counter()
        api_latency = round((end_time - start_time) * 1000, 2)
        
        # 2. Measure Gateway (WebSocket) latency
        ws_latency = round(self.bot.latency * 1000)
        
        # 3. Measure Database latency (if possible)
        db_latency = 0
        if self.bot.db:
            db_start = time.perf_counter()
            await self.bot.db.execute("SELECT 1")
            db_end = time.perf_counter()
            db_latency = round((db_end - db_start) * 1000, 2)
            
        shard_id = ctx.guild.shard_id if ctx.guild else 0
        
        embed = discord.Embed(
            title=f"Cluster {shard_id or random.randint(10, 99)}",
            color=discord.Color.dark_theme()
        )
        
        desc = (
            f"• **Discord REST latency:** {api_latency} ms\n"
            f"• **Discord Gateway (WS) latency:** {ws_latency} ms (Shard `{shard_id or 0}`)\n"
        )
        
        if self.bot.db:
            desc += f"• **Database response time:** {db_latency} ms\n"
            
        embed.description = desc
        
        await message.edit(content=None, embed=embed)

    @commands.command(name="meme")
    async def meme(self, ctx: commands.Context):
        await ctx.send(random.choice(MEMES))

    @commands.command(name="8ball")
    async def eight_ball(self, ctx: commands.Context, *, question: str = ""):
        await ctx.send(f"🎱 {random.choice(EIGHTBALL)}")

    @commands.command(name="chat")
    async def chat(self, ctx: commands.Context, *, message: str):
        replies = [
            "Interesting...",
            "Tell me more.",
            "Why do you think that?",
            "Understood.",
            "Logged to neural core.",
        ]
        await ctx.send(random.choice(replies))


async def setup(bot: commands.Bot):
    await bot.add_cog(FunCog(bot))
