# cogs/invite_tracker.py
import discord
from discord.ext import commands
from discord import app_commands


class InviteTrackerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._invite_cache: dict[int, dict[str, int]] = {}  # guild_id -> {code: uses}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                invites = await guild.invites()
                self._invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        guild_id = invite.guild.id
        if guild_id not in self._invite_cache:
            self._invite_cache[guild_id] = {}
        self._invite_cache[guild_id][invite.code] = invite.uses

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        guild_id = invite.guild.id
        if guild_id in self._invite_cache:
            self._invite_cache[guild_id].pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        try:
            new_invites = await guild.invites()
        except discord.Forbidden:
            return

        old_cache = self._invite_cache.get(guild.id, {})
        used_invite = None

        for inv in new_invites:
            old_uses = old_cache.get(inv.code, 0)
            if inv.uses > old_uses:
                used_invite = inv
                break

        # Update cache
        self._invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}

        if used_invite and used_invite.inviter:
            inviter = used_invite.inviter
            await self.bot.db.execute(
                """INSERT INTO member_invites (user_id, guild_id, invited_by) VALUES (?,?,?)
                   ON CONFLICT(user_id, guild_id) DO UPDATE SET invited_by=excluded.invited_by""",
                (member.id, guild.id, inviter.id)
            )
            # Update invite_tracker table
            await self.bot.db.execute(
                """INSERT INTO invite_tracker (invite_code, guild_id, inviter_id, uses) VALUES (?,?,?,1)
                   ON CONFLICT(invite_code, guild_id) DO UPDATE SET uses = uses + 1""",
                (used_invite.code, guild.id, inviter.id)
            )
            await self.bot.db.commit()

    # ---------- /invites ----------

    @app_commands.command(name="invites", description="Check how many members a user has invited.")
    @app_commands.describe(member="User to check (optional, defaults to you).")
    async def invites(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        cur = await self.bot.db.execute(
            "SELECT SUM(uses) FROM invite_tracker WHERE guild_id=? AND inviter_id=?",
            (interaction.guild.id, target.id)
        )
        row = await cur.fetchone()
        total = row[0] or 0
        embed = discord.Embed(
            title=f"📨 Invites — {target.display_name}",
            description=f"**{target.display_name}** has invited **{total}** member(s) to this server.",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ---------- /invite_leaderboard ----------

    @app_commands.command(name="invite_leaderboard", description="View the top inviters in this server.")
    async def invite_leaderboard(self, interaction: discord.Interaction):
        cur = await self.bot.db.execute(
            "SELECT inviter_id, SUM(uses) as total FROM invite_tracker WHERE guild_id=? GROUP BY inviter_id ORDER BY total DESC LIMIT 10",
            (interaction.guild.id,)
        )
        rows = await cur.fetchall()
        embed = discord.Embed(title="📨 Invite Leaderboard", color=discord.Color.green())
        medals = ["🥇", "🥈", "🥉"]
        desc = ""
        for i, (uid, total) in enumerate(rows):
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            m = interaction.guild.get_member(uid)
            name = m.display_name if m else f"User {uid}"
            desc += f"{medal} **{name}** — {total} invite(s)\n"
        embed.description = desc or "No invite data yet."
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(InviteTrackerCog(bot))
