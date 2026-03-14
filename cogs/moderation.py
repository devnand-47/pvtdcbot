# cogs/moderation.py

import discord
from discord.ext import commands
from discord import app_commands

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


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="kick", description="Kick a member.")
    @is_admin()
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
    ):
        await member.kick(reason=reason)
        await interaction.response.send_message(
            f"👢 Kicked {member} | Reason: {reason}", ephemeral=True
        )

    @app_commands.command(name="ban", description="Ban a member.")
    @is_admin()
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided",
    ):
        await member.ban(reason=reason, delete_message_days=1)
        await interaction.response.send_message(
            f"🔨 Banned {member} | Reason: {reason}", ephemeral=True
        )

    @app_commands.command(name="mute", description="Timeout a member.")
    @is_admin()
    @app_commands.describe(minutes="Duration in minutes.")
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        minutes: app_commands.Range[int, 1, 43200],  # up to 30 days
        reason: str = "No reason provided",
    ):
        duration = discord.utils.utcnow() + discord.timedelta(minutes=minutes)
        await member.timeout_until(duration, reason=reason)
        await interaction.response.send_message(
            f"🔇 Muted {member} for {minutes} minutes.", ephemeral=True
        )

    @app_commands.command(name="unmute", description="Remove timeout.")
    @is_admin()
    async def unmute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        await member.timeout_until(None, reason="Manual unmute")
        await interaction.response.send_message(
            f"🔊 Unmuted {member}.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))
