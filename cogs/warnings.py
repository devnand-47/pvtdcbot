# cogs/warnings.py
import time
import discord
from discord.ext import commands
from discord import app_commands
from config import ADMIN_ROLE_IDS, LOG_CHANNEL_ID


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


class WarningsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_cfg(self, guild_id):
        cur = await self.bot.db.execute(
            "SELECT mute_at, kick_at, ban_at FROM warning_config WHERE guild_id=?", (guild_id,)
        )
        row = await cur.fetchone()
        return row if row else (3, 5, 7)

    async def count_warnings(self, guild_id, user_id):
        cur = await self.bot.db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        row = await cur.fetchone()
        return row[0] if row else 0

    async def _log(self, guild, actor, target, action, reason):
        log_ch = guild.get_channel(LOG_CHANNEL_ID)
        if isinstance(log_ch, discord.TextChannel):
            embed = discord.Embed(
                title=f"⚠️ {action}",
                description=f"**Target:** {target.mention}\n**Actor:** {actor.mention}\n**Reason:** {reason}",
                color=discord.Color.orange()
            )
            embed.timestamp = discord.utils.utcnow()
            await log_ch.send(embed=embed)

    # ---------- /warn ----------

    @app_commands.command(name="warn", description="Issue a warning to a member.")
    @is_admin()
    @app_commands.describe(member="Member to warn.", reason="Reason for the warning.")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        now = int(time.time())
        await self.bot.db.execute(
            "INSERT INTO warnings (guild_id, user_id, actor_id, reason, created_at) VALUES (?,?,?,?,?)",
            (interaction.guild.id, member.id, interaction.user.id, reason, now)
        )
        await self.bot.db.commit()

        count = await self.count_warnings(interaction.guild.id, member.id)
        mute_at, kick_at, ban_at = await self.get_cfg(interaction.guild.id)

        embed = discord.Embed(
            title="⚠️ Warning Issued",
            description=f"{member.mention} has been warned.\n**Reason:** {reason}\n**Total warnings:** {count}",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)

        # Try to DM the user
        try:
            await member.send(f"⚠️ You received a warning in **{interaction.guild.name}**.\n**Reason:** {reason}\nTotal warnings: {count}")
        except Exception:
            pass

        # Auto-actions
        if count >= ban_at:
            try:
                await member.ban(reason=f"Auto-ban: {count} warnings")
                await interaction.channel.send(f"🔨 {member.mention} auto-banned after {count} warnings.")
            except discord.Forbidden:
                pass
        elif count >= kick_at:
            try:
                await member.kick(reason=f"Auto-kick: {count} warnings")
                await interaction.channel.send(f"👢 {member.mention} auto-kicked after {count} warnings.")
            except discord.Forbidden:
                pass
        elif count >= mute_at:
            from datetime import timedelta
            try:
                await member.timeout(timedelta(hours=1), reason=f"Auto-mute: {count} warnings")
                await interaction.channel.send(f"🔇 {member.mention} auto-muted (1h) after {count} warnings.")
            except discord.Forbidden:
                pass

        await self._log(interaction.guild, interaction.user, member, "Warning Issued", reason)

    # ---------- /warnings ----------

    @app_commands.command(name="warnings", description="View all warnings for a member.")
    @app_commands.describe(member="Member to check.")
    async def warnings_view(self, interaction: discord.Interaction, member: discord.Member):
        cur = await self.bot.db.execute(
            "SELECT id, reason, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY created_at DESC",
            (interaction.guild.id, member.id)
        )
        rows = await cur.fetchall()
        embed = discord.Embed(title=f"⚠️ Warnings for {member.display_name}", color=discord.Color.orange())
        embed.set_thumbnail(url=member.display_avatar.url)
        if not rows:
            embed.description = "No warnings."
        else:
            for wid, reason, ts in rows:
                embed.add_field(name=f"ID `{wid}` — <t:{ts}:d>", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    # ---------- /clearwarn ----------

    @app_commands.command(name="clearwarn", description="Remove a specific warning by ID.")
    @is_admin()
    @app_commands.describe(warning_id="The ID of the warning to remove.")
    async def clearwarn(self, interaction: discord.Interaction, warning_id: int):
        await self.bot.db.execute(
            "DELETE FROM warnings WHERE id=? AND guild_id=?", (warning_id, interaction.guild.id)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"🗑️ Warning `#{warning_id}` removed.", ephemeral=True)

    # ---------- /clearwarns ----------

    @app_commands.command(name="clearwarns", description="Clear ALL warnings for a member.")
    @is_admin()
    @app_commands.describe(member="Member to clear warnings for.")
    async def clearwarns(self, interaction: discord.Interaction, member: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?",
            (interaction.guild.id, member.id)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ All warnings cleared for {member.mention}.", ephemeral=True)

    # ---------- /warn_config ----------

    @app_commands.command(name="warn_config", description="Set auto-action thresholds for warnings. (Admin)")
    @is_admin()
    @app_commands.describe(mute_at="Warnings to auto-mute.", kick_at="Warnings to auto-kick.", ban_at="Warnings to auto-ban.")
    async def warn_config(self, interaction: discord.Interaction, mute_at: int = 3, kick_at: int = 5, ban_at: int = 7):
        await self.bot.db.execute(
            """INSERT INTO warning_config (guild_id, mute_at, kick_at, ban_at) VALUES (?,?,?,?)
               ON CONFLICT(guild_id) DO UPDATE SET mute_at=excluded.mute_at, kick_at=excluded.kick_at, ban_at=excluded.ban_at""",
            (interaction.guild.id, mute_at, kick_at, ban_at)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(
            f"✅ Thresholds set: Mute at {mute_at} warnings, Kick at {kick_at}, Ban at {ban_at}.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(WarningsCog(bot))
