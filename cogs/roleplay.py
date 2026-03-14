# cogs/roleplay.py
import discord
import aiohttp
from discord.ext import commands
from discord import app_commands


class RoleplayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def fetch_gif(self, action: str) -> str:
        url = f"https://nekos.life/api/v2/img/{action}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("url")
        except Exception:
            pass
        return None

    async def build_rp_embed(self, action: str, author: discord.Member, target: discord.Member, title_text: str) -> discord.Embed:
        gif_url = await self.fetch_gif(action)
        embed = discord.Embed(
            description=f"**{author.display_name}** {title_text} **{target.display_name}**!",
            color=discord.Color.from_rgb(255, 105, 180)
        )
        if gif_url:
            embed.set_image(url=gif_url)
        return embed

    # ---------- /hug ----------

    @app_commands.command(name="hug", description="Give someone a big hug!")
    @app_commands.describe(member="The user you want to hug.")
    async def hug(self, interaction: discord.Interaction, member: discord.Member):
        if member.id == interaction.user.id:
            await interaction.response.send_message("You hugged yourself. *pat pat*", ephemeral=True)
            return
        
        await interaction.response.defer()
        embed = await self.build_rp_embed("hug", interaction.user, member, "gives a big hug to")
        await interaction.followup.send(content=member.mention, embed=embed)

    # ---------- /slap ----------

    @app_commands.command(name="slap", description="Slap some sense into someone!")
    @app_commands.describe(member="The user you want to slap.")
    async def slap(self, interaction: discord.Interaction, member: discord.Member):
        if member.id == interaction.user.id:
            await interaction.response.send_message("Why are you slapping yourself?", ephemeral=True)
            return

        await interaction.response.defer()
        embed = await self.build_rp_embed("slap", interaction.user, member, "slaps")
        embed.color = discord.Color.red()
        await interaction.followup.send(content=member.mention, embed=embed)

    # ---------- /pat ----------

    @app_commands.command(name="pat", description="Pat someone on the head.")
    @app_commands.describe(member="The user you want to pat.")
    async def pat(self, interaction: discord.Interaction, member: discord.Member):
        if member.id == interaction.user.id:
            await interaction.response.send_message("You pat yourself on the head. Good job.", ephemeral=True)
            return

        await interaction.response.defer()
        embed = await self.build_rp_embed("pat", interaction.user, member, "gently pats")
        embed.color = discord.Color.brand_green()
        await interaction.followup.send(content=member.mention, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleplayCog(bot))
