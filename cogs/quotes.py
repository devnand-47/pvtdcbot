# cogs/quotes.py
import time
import discord
import random
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


class QuotesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- /quote add ----------

    @app_commands.command(name="quote_add", description="Save a memorable quote from someone.")
    @app_commands.describe(member="Who said it.", content="The quote text.")
    async def quote_add(self, interaction: discord.Interaction, member: discord.Member, content: str):
        now = int(time.time())
        await self.bot.db.execute(
            "INSERT INTO quotes (guild_id, user_id, quoted_user_id, content, created_at) VALUES (?,?,?,?,?)",
            (interaction.guild.id, interaction.user.id, member.id, content, now)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(
            f"📖 Saved quote from **{member.display_name}**: *\"{content}\"*"
        )

    # ---------- /quote random ----------

    @app_commands.command(name="quote", description="Retrieve a random saved quote.")
    async def quote_random(self, interaction: discord.Interaction):
        cur = await self.bot.db.execute(
            "SELECT id, quoted_user_id, content, created_at FROM quotes WHERE guild_id=? ORDER BY RANDOM() LIMIT 1",
            (interaction.guild.id,)
        )
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message("📖 No quotes saved yet! Use `/quote_add` to save one.", ephemeral=True)
            return

        qid, quoted_uid, content, ts = row
        member = interaction.guild.get_member(quoted_uid)
        name = member.display_name if member else f"User {quoted_uid}"
        avatar = member.display_avatar.url if member else None

        embed = discord.Embed(
            description=f'*"{content}"*',
            color=discord.Color.teal(),
            timestamp=discord.utils.utcfromtimestamp(ts)
        )
        embed.set_author(name=name, icon_url=avatar)
        embed.set_footer(text=f"Quote #{qid}")
        await interaction.response.send_message(embed=embed)

    # ---------- /quote_list ----------

    @app_commands.command(name="quote_list", description="View the last 10 saved quotes.")
    async def quote_list(self, interaction: discord.Interaction):
        cur = await self.bot.db.execute(
            "SELECT id, quoted_user_id, content FROM quotes WHERE guild_id=? ORDER BY created_at DESC LIMIT 10",
            (interaction.guild.id,)
        )
        rows = await cur.fetchall()
        embed = discord.Embed(title="📖 Quote Archive", color=discord.Color.teal())
        if not rows:
            embed.description = "No quotes saved yet."
        else:
            for qid, uid, content in rows:
                m = interaction.guild.get_member(uid)
                name = m.display_name if m else f"User {uid}"
                embed.add_field(name=f"`#{qid}` — {name}", value=f'*"{content[:80]}"*', inline=False)
        await interaction.response.send_message(embed=embed)

    # ---------- /quote_remove ----------

    @app_commands.command(name="quote_remove", description="Remove a quote by ID. (Admin)")
    @is_admin()
    @app_commands.describe(quote_id="ID of the quote to remove.")
    async def quote_remove(self, interaction: discord.Interaction, quote_id: int):
        await self.bot.db.execute(
            "DELETE FROM quotes WHERE id=? AND guild_id=?", (quote_id, interaction.guild.id)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"🗑️ Quote `#{quote_id}` removed.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(QuotesCog(bot))
