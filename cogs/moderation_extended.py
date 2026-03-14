# cogs/moderation_extended.py
import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta
import re
from config import ADMIN_ROLE_IDS, LOG_CHANNEL_ID
import time


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


def parse_duration(raw: str) -> timedelta | None:
    """Parses strings like '10m', '2h', '1d' into timedelta."""
    m = re.fullmatch(r"(\d+)([smhd])", raw.strip().lower())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return timedelta(seconds=val * units[unit])


class ModerationExtendedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _log(self, guild: discord.Guild, actor: discord.Member, target: discord.Member, action: str, reason: str, duration: str):
        """Log the action to moderation_logs and the log channel."""
        if self.bot.db:
            await self.bot.db.execute(
                "INSERT INTO moderation_logs (guild_id, user_id, actor_id, action, reason, created_at) VALUES (?,?,?,?,?,?)",
                (guild.id, target.id, actor.id, action, f"{reason} | Duration: {duration}", int(time.time()))
            )
            await self.bot.db.commit()

        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if isinstance(log_channel, discord.TextChannel):
            embed = discord.Embed(
                title=f"🔨 {action.title()}",
                description=f"**Target:** {target.mention} (`{target.id}`)\n**Actor:** {actor.mention}\n**Duration:** {duration}\n**Reason:** {reason}",
                color=discord.Color.red()
            )
            embed.timestamp = discord.utils.utcnow()
            await log_channel.send(embed=embed)

    # ---------- /tempmute ----------

    @app_commands.command(name="tempmute", description="Temporarily mute a user using Discord's native timeout.")
    @is_admin()
    @app_commands.describe(
        member="User to mute.",
        duration="Duration: 10s, 5m, 2h, 1d (max 28d).",
        reason="Reason for muting."
    )
    async def tempmute(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason provided"):
        delta = parse_duration(duration)
        if not delta:
            await interaction.response.send_message("❌ Invalid duration. Use formats like `10s`, `5m`, `2h`, `1d`.", ephemeral=True)
            return
        if delta > timedelta(days=28):
            await interaction.response.send_message("❌ Maximum timeout is 28 days.", ephemeral=True)
            return

        try:
            await member.timeout(delta, reason=reason)
            await interaction.response.send_message(
                f"🔇 **{member.display_name}** has been timed out for **{duration}**.\n**Reason:** {reason}",
                ephemeral=False
            )
            await self._log(interaction.guild, interaction.user, member, "tempmute", reason, duration)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to timeout that user.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    # ---------- /tempban ----------

    @app_commands.command(name="tempban", description="Ban a user and automatically unban after the specified duration.")
    @is_admin()
    @app_commands.describe(
        member="User to temp-ban.",
        duration="Duration: e.g. 10m, 2h, 3d.",
        reason="Reason."
    )
    async def tempban(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "Temp-ban"):
        delta = parse_duration(duration)
        if not delta:
            await interaction.response.send_message("❌ Invalid duration. Use `10m`, `2h`, `3d` format.", ephemeral=True)
            return

        try:
            await member.ban(reason=f"{reason} (temp-ban {duration})")
            await interaction.response.send_message(
                f"🔨 **{member.display_name}** has been banned for **{duration}**.\n**Reason:** {reason}",
                ephemeral=False
            )
            await self._log(interaction.guild, interaction.user, member, "tempban", reason, duration)

            # Schedule unban
            import asyncio
            user_id = member.id
            guild = interaction.guild

            async def _unban():
                await asyncio.sleep(delta.total_seconds())
                try:
                    user = await self.bot.fetch_user(user_id)
                    await guild.unban(user, reason=f"Auto-unban after {duration}")
                    log_ch = guild.get_channel(LOG_CHANNEL_ID)
                    if isinstance(log_ch, discord.TextChannel):
                        await log_ch.send(f"🔓 Auto-unbanned <@{user_id}> after temp-ban of {duration}.")
                except Exception as e:
                    print(f"[TempBan] Failed to auto-unban {user_id}: {e}")

            asyncio.create_task(_unban())

        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to ban that user.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationExtendedCog(bot))
