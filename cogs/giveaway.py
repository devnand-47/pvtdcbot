# cogs/giveaway.py
import asyncio
import random
import time
import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional
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


def parse_seconds(raw: str) -> int | None:
    import re
    m = re.fullmatch(r"(\d+)([smhd])", raw.strip().lower())
    if not m:
        return None
    val, unit = int(m.group(1)), m.group(2)
    return val * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


class GiveawayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    @tasks.loop(seconds=10)
    async def check_giveaways(self):
        if not self.bot.db:
            return
        now = int(time.time())
        cur = await self.bot.db.execute(
            "SELECT id, guild_id, channel_id, message_id, prize, winners FROM giveaways WHERE ends_at <= ? AND ended = 0",
            (now,)
        )
        rows = await cur.fetchall()
        for row in rows:
            g_id, guild_id, channel_id, message_id, prize, winners_count = row
            await self._end_giveaway(g_id, guild_id, channel_id, message_id, prize, winners_count)

    @check_giveaways.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _end_giveaway(self, g_id, guild_id, channel_id, message_id, prize, winners_count):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            msg = await channel.fetch_message(message_id)
        except Exception:
            return

        # Get 🎉 reactors
        reactors = []
        for reaction in msg.reactions:
            if str(reaction.emoji) == "🎉":
                async for user in reaction.users():
                    if not user.bot:
                        reactors.append(user)
                break

        await self.bot.db.execute("UPDATE giveaways SET ended = 1 WHERE id = ?", (g_id,))
        await self.bot.db.commit()

        if not reactors:
            await channel.send(f"🎉 Giveaway for **{prize}** ended — no valid entries!")
            return

        picked = random.sample(reactors, min(winners_count, len(reactors)))
        mentions = ", ".join(w.mention for w in picked)

        embed = discord.Embed(
            title="🎉 Giveaway Ended!",
            description=f"**Prize:** {prize}\n**Winner(s):** {mentions}\n\nCongratulations! 🏆",
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Giveaway ID: {message_id}")
        await channel.send(content=mentions, embed=embed)

        # Update original message
        ended_embed = discord.Embed(
            title="🎉 GIVEAWAY — ENDED",
            description=f"**Prize:** {prize}\n**Winner(s):** {mentions}",
            color=discord.Color.greyple()
        )
        ended_embed.set_footer(text="This giveaway has ended.")
        try:
            await msg.edit(embed=ended_embed)
        except Exception:
            pass

    @app_commands.command(name="giveaway", description="Start a giveaway.")
    @is_admin()
    @app_commands.describe(
        duration="Duration: e.g. 30s, 10m, 2h, 1d",
        prize="What are you giving away?",
        winners="Number of winners (default 1).",
        channel="Channel to post in (optional)."
    )
    async def giveaway(self, interaction: discord.Interaction, duration: str, prize: str, winners: int = 1, channel: Optional[discord.TextChannel] = None):
        seconds = parse_seconds(duration)
        if not seconds or seconds < 5:
            await interaction.response.send_message("❌ Invalid duration. Use `30s`, `10m`, `2h`, `1d`.", ephemeral=True)
            return

        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("❌ Invalid channel.", ephemeral=True)
            return

        ends_at = int(time.time()) + seconds
        embed = discord.Embed(
            title="🎉 GIVEAWAY!",
            description=f"**Prize:** {prize}\n\nReact with 🎉 to enter!\n\n**Ends:** <t:{ends_at}:R>\n**Winners:** {winners}",
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Hosted by {interaction.user.display_name}")

        msg = await target.send(embed=embed)
        await msg.add_reaction("🎉")

        await self.bot.db.execute(
            "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, winners, ends_at, ended) VALUES (?,?,?,?,?,?,0)",
            (interaction.guild.id, target.id, msg.id, prize, winners, ends_at)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Giveaway started in {target.mention}!", ephemeral=True)

    @app_commands.command(name="giveaway_reroll", description="Reroll a giveaway winner.")
    @is_admin()
    @app_commands.describe(message_id="Message ID of the ended giveaway.")
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            mid = int(message_id)
            msg = await interaction.channel.fetch_message(mid)
        except Exception:
            await interaction.followup.send("❌ Could not find that message.", ephemeral=True)
            return

        reactors = []
        for reaction in msg.reactions:
            if str(reaction.emoji) == "🎉":
                async for user in reaction.users():
                    if not user.bot:
                        reactors.append(user)
                break

        if not reactors:
            await interaction.followup.send("❌ No valid entries found to reroll.", ephemeral=True)
            return

        winner = random.choice(reactors)
        await interaction.channel.send(f"🔄 **Reroll!** New winner: {winner.mention} 🎉")
        await interaction.followup.send("✅ Rerolled.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayCog(bot))
