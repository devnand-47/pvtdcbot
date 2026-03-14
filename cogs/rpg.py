# cogs/rpg.py
import discord
import random
import time
from discord.ext import commands
from discord import app_commands


class RPGCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    rpg = app_commands.Group(name="rpg", description="RPG and Pet commands")

    async def get_eco(self):
        return self.bot.cogs.get("EconomyCog")

    # ---------- /pet_buy ----------

    @rpg.command(name="pet_buy", description="Buy an RPG pet to help you find coins.")
    @app_commands.describe(pet_name="Give your new pet a name!")
    async def pet_buy(self, interaction: discord.Interaction, pet_name: str):
        eco = await self.get_eco()
        if not eco:
            return

        cur = await self.bot.db.execute("SELECT name FROM pets WHERE user_id=?", (interaction.user.id,))
        if await cur.fetchone():
            await interaction.response.send_message("❌ You already own a pet!", ephemeral=True)
            return

        cost = 5000
        if not await eco.take_coins(interaction.user.id, interaction.guild.id, cost):
            await interaction.response.send_message(f"❌ You need **{cost:,} 🪙** to buy a pet.", ephemeral=True)
            return

        pet_type = random.choice(["🐶 Dog", "🐱 Cat", "🐉 Dragon", "🐺 Wolf", "🦊 Fox"])
        await self.bot.db.execute(
            "INSERT INTO pets (user_id, name, type, level, exp) VALUES (?, ?, ?, 1, 0)",
            (interaction.user.id, pet_name, pet_type)
        )
        await self.bot.db.commit()

        embed = discord.Embed(
            title="🐾 Pet Adopted!",
            description=f"You successfully adopted **{pet_name}** the **{pet_type}**!\nTake them on quests to level them up.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    # ---------- /pet_info ----------

    @rpg.command(name="pet_info", description="Check your pet's stats.")
    async def pet_info(self, interaction: discord.Interaction):
        cur = await self.bot.db.execute("SELECT name, type, level, exp FROM pets WHERE user_id=?", (interaction.user.id,))
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message("❌ You don't have a pet yet! Use `/pet_buy`.", ephemeral=True)
            return

        name, p_type, level, exp = row
        next_lvl = level * 100

        embed = discord.Embed(title=f"🐾 {name}'s Stats", color=discord.Color.gold())
        embed.add_field(name="Type", value=p_type, inline=True)
        embed.add_field(name="Level", value=f"**{level}**", inline=True)
        embed.add_field(name="Experience", value=f"{exp} / {next_lvl} XP", inline=True)
        await interaction.response.send_message(embed=embed)

    # ---------- /quest ----------

    @rpg.command(name="quest", description="Go on an adventure to earn coins and pet XP.")
    @app_commands.checks.cooldown(1, 300, key=lambda i: i.user.id) # 5m cooldown
    async def quest(self, interaction: discord.Interaction):
        eco = await self.get_eco()
        
        cur = await self.bot.db.execute("SELECT name, type, level, exp FROM pets WHERE user_id=?", (interaction.user.id,))
        row = await cur.fetchone()
        
        pet_multiplier = 1.0
        pet_str = ""

        if row:
            name, p_type, level, exp = row
            pet_multiplier = 1.0 + (level * 0.05)
            new_exp = exp + random.randint(10, 30)
            next_lvl = level * 100
            if new_exp >= next_lvl:
                await self.bot.db.execute("UPDATE pets SET level=level+1, exp=0 WHERE user_id=?", (interaction.user.id,))
                pet_str = f"\n🆙 Your pet **{name}** leveled up to **Level {level+1}**!"
            else:
                await self.bot.db.execute("UPDATE pets SET exp=? WHERE user_id=?", (new_exp, interaction.user.id,))
                pet_str = f"\n🐾 **{name}** helped you and gained XP!"
            await self.bot.db.commit()

        success_chance = 0.8
        if random.random() < success_chance:
            base_reward = random.randint(100, 500)
            total_reward = int(base_reward * pet_multiplier)
            if eco:
                await eco.add_coins(interaction.user.id, interaction.guild.id, total_reward)
            
            scenarios = [
                "You defeated a band of goblins and stole their stash!",
                "You found a hidden treasure chest in the spooky woods.",
                "You rescued a merchant who tipped you generously.",
                "You mined some rare gems in the crystal caves."
            ]
            embed = discord.Embed(
                title="🗺️ Quest Complete!",
                description=f"{random.choice(scenarios)}\n\n💰 **Found:** {total_reward:,} 🪙{pet_str}",
                color=discord.Color.green()
            )
        else:
            scenarios = [
                "You fell into a trap and lost your way.",
                "A dragon chased you out of the mountains.",
                "Bandits ambushed you and you had to flee.",
                "You spent hours searching but found absolutely nothing."
            ]
            embed = discord.Embed(
                title="☠️ Quest Failed!",
                description=f"{random.choice(scenarios)}\n\nYou earned **0 🪙**.{pet_str}",
                color=discord.Color.red()
            )

        await interaction.response.send_message(embed=embed)

    @quest.error
    async def quest_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(f"⌛ You are resting. Try again in **{int(error.retry_after)}s**.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RPGCog(bot))
