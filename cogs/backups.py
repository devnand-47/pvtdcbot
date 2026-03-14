# cogs/backups.py

import os
import time

import discord
from discord.ext import commands, tasks
from discord import app_commands

from config import BACKUP_ROOT, BACKUP_MESSAGES_PER_CHANNEL, ADMIN_ROLE_IDS


def is_admin():
    async def predicate(interaction: discord.Interaction):
        member = interaction.user
        if isinstance(member, discord.Member):
            if member.guild_permissions.administrator:
                return True
            if any(r.id in ADMIN_ROLE_IDS for r in member.roles):
                return True
        await interaction.response.send_message(
            "❌ Admin only.", ephemeral=True
        )
        raise app_commands.CheckFailure("Not admin")

    return app_commands.check(predicate)


class BackupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        os.makedirs(BACKUP_ROOT, exist_ok=True)
        self.monthly_backup_loop.start()

    def cog_unload(self):
        self.monthly_backup_loop.cancel()

    async def backup_guild(self, guild: discord.Guild):
        now = time.localtime()
        month_dir = os.path.join(
            BACKUP_ROOT, str(guild.id), f"{now.tm_year}-{now.tm_mon:02d}"
        )
        os.makedirs(month_dir, exist_ok=True)

        for channel in guild.text_channels:
            filename = os.path.join(
                month_dir, f"{channel.name}_{channel.id}.txt"
            )
            lines = []
            async for msg in channel.history(
                limit=BACKUP_MESSAGES_PER_CHANNEL, oldest_first=True
            ):
                timestamp = msg.created_at.isoformat()
                author = f"{msg.author} ({msg.author.id})"
                content = msg.content.replace("\n", "\\n")
                lines.append(f"[{timestamp}] {author}: {content}")

            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

    @app_commands.command(
        name="backup_now",
        description="Run a backup of this guild's text channels.",
    )
    @is_admin()
    async def backup_now(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Guild not found.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "⏳ Starting backup in background...", ephemeral=True
        )
        await self.backup_guild(guild)
        await interaction.followup.send(
            "✅ Backup complete (stored on VPS).", ephemeral=True
        )

    @tasks.loop(hours=24)
    async def monthly_backup_loop(self):
        if not self.bot.is_ready():
            return

        now = time.gmtime()
        if now.tm_mday != 1:
            return

        for guild in self.bot.guilds:
            await self.backup_guild(guild)

    @monthly_backup_loop.before_loop
    async def before_monthly_backup_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupCog(bot))
