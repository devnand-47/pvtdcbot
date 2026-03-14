# cogs/image_memes.py
import discord
from discord.ext import commands
from discord import app_commands


class ImageMemesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    img = app_commands.Group(name="img", description="Image manipulation commands")

    def get_avatar_url(self, member: discord.Member) -> str:
        # We need a generic image URL. Discord avatars usually end in .webp or .png with a query string.
        # We replace the format with .png to ensure it renders correctly in most external image APIs.
        url = member.display_avatar.url
        if ".webp" in url:
            url = url.split("?")[0] + "?size=256"
            url = url.replace(".webp", ".png")
        return url

    # ---------- /img wanted ----------

    @img.command(name="wanted", description="Put someone on a Wanted poster.")
    @app_commands.describe(member="The target.")
    async def wanted(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        avatar = self.get_avatar_url(target)
        
        # Using popcat API for fast image manipulation
        # Example: https://api.popcat.xyz/wanted?image=URL
        image_url = f"https://api.popcat.xyz/wanted?image={avatar}"
        
        embed = discord.Embed(title=f"🚨 WANTED: {target.display_name}", color=discord.Color.dark_theme())
        embed.set_image(url=image_url)
        await interaction.response.send_message(embed=embed)

    # ---------- /img jail ----------

    @img.command(name="jail", description="Put someone behind bars.")
    @app_commands.describe(member="The target.")
    async def jail(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        avatar = self.get_avatar_url(target)
        
        image_url = f"https://api.popcat.xyz/jail?image={avatar}"
        
        embed = discord.Embed(title=f"🚔 BUSTED: {target.display_name}", color=discord.Color.dark_grey())
        embed.set_image(url=image_url)
        await interaction.response.send_message(embed=embed)

    # ---------- /img wasted ----------

    @img.command(name="wasted", description="Apply the GTA Wasted effect to an avatar.")
    @app_commands.describe(member="The target.")
    async def wasted(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        avatar = self.get_avatar_url(target)
        
        # Note: Popcat doesn't have wasted natively, but some APIs might. We'll use a grayscale + overlay if possible.
        # Popcat has 'drip' and 'unforgivable'. Let's use unforgivable for dramatic effect.
        image_url = f"https://api.popcat.xyz/greyscale?image={avatar}" 
        
        embed = discord.Embed(title=f"💀 WASTED: {target.display_name}", color=discord.Color.dark_red())
        embed.set_image(url=image_url)
        await interaction.response.send_message(embed=embed)

    # ---------- /img clown ----------

    @img.command(name="clown", description="Expose the clown!")
    @app_commands.describe(member="The target.")
    async def clown(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        avatar = self.get_avatar_url(target)
        
        image_url = f"https://api.popcat.xyz/clown?image={avatar}" 
        
        embed = discord.Embed(title=f"🤡 Absolute Clown: {target.display_name}", color=discord.Color.red())
        embed.set_image(url=image_url)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ImageMemesCog(bot))
