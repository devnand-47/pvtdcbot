# cogs/marriage.py
import discord
import time
from discord.ext import commands
from discord import app_commands


class MarriageCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_eco(self):
        return self.bot.cogs.get("EconomyCog")

    # ---------- /marry ----------

    @app_commands.command(name="marry", description="Propose to another user!")
    @app_commands.describe(user="The user you want to marry.")
    async def marry(self, interaction: discord.Interaction, user: discord.Member):
        if user.id == interaction.user.id:
            await interaction.response.send_message("❌ You can't marry yourself!", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("❌ Bots don't have feelings.", ephemeral=True)
            return

        cur = await self.bot.db.execute("SELECT * FROM marriages WHERE user1_id=? OR user2_id=?", (interaction.user.id, interaction.user.id))
        if await cur.fetchone():
            await interaction.response.send_message("❌ You are already married! Get a divorce first.", ephemeral=True)
            return

        cur = await self.bot.db.execute("SELECT * FROM marriages WHERE user1_id=? OR user2_id=?", (user.id, user.id))
        if await cur.fetchone():
            await interaction.response.send_message(f"❌ **{user.display_name}** is already married to someone else.", ephemeral=True)
            return

        cost = 10000
        eco = await self.get_eco()
        if eco and not await eco.take_coins(interaction.user.id, interaction.guild.id, cost):
            await interaction.response.send_message(f"❌ You need a ring! A ring costs **{cost:,} 🪙**.", ephemeral=True)
            return

        class ProposalView(discord.ui.View):
            def __init__(self, bot):
                super().__init__(timeout=60)
                self.bot = bot

            @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="💍")
            async def _accept(self, idx: discord.Interaction, btn: discord.ui.Button):
                if idx.user.id != user.id:
                    await idx.response.send_message("This proposal isn't for you!", ephemeral=True)
                    return
                for child in self.children:
                    child.disabled = True
                
                now = int(time.time())
                await self.bot.db.execute("INSERT INTO marriages (user1_id, user2_id, married_at) VALUES (?,?,?)", (interaction.user.id, user.id, now))
                await self.bot.db.commit()

                em = discord.Embed(
                    title="💍 Just Married!",
                    description=f"**{interaction.user.mention}** and **{user.mention}** are now officially married! 🎉",
                    color=discord.Color.from_rgb(255, 105, 180)
                )
                await idx.response.edit_message(embed=em, view=self)

            @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
            async def _decline(self, idx: discord.Interaction, btn: discord.ui.Button):
                if idx.user.id != user.id:
                    return
                for child in self.children:
                    child.disabled = True
                
                # Refund the ring
                if eco:
                    await eco.add_coins(interaction.user.id, interaction.guild.id, cost)
                    
                em = discord.Embed(title="💔 Rejected", description=f"**{user.display_name}** declined the proposal...", color=discord.Color.dark_grey())
                await idx.response.edit_message(embed=em, view=self)

        embed = discord.Embed(
            title="💍 Wedding Proposal",
            description=f"{user.mention}, **{interaction.user.display_name}** has bought a ring ({cost} 🪙) and asked you to marry them!\n\nDo you accept?",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(f"{user.mention}", embed=embed, view=ProposalView(self.bot))

    # ---------- /divorce ----------

    @app_commands.command(name="divorce", description="Divorce your current partner.")
    async def divorce(self, interaction: discord.Interaction):
        cur = await self.bot.db.execute("SELECT user1_id, user2_id FROM marriages WHERE user1_id=? OR user2_id=?", (interaction.user.id, interaction.user.id))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message("❌ You aren't married.", ephemeral=True)
            return

        partner_id = row[1] if row[0] == interaction.user.id else row[0]
        await self.bot.db.execute("DELETE FROM marriages WHERE user1_id=? OR user2_id=?", (interaction.user.id, interaction.user.id))
        await self.bot.db.commit()

        embed = discord.Embed(
            title="💔 Divorced",
            description=f"You are officially divorced from <@{partner_id}>. You're single again.",
            color=discord.Color.dark_theme()
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MarriageCog(bot))
