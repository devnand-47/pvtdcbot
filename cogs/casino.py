# cogs/casino.py
import discord
import random
import asyncio
from discord.ext import commands
from discord import app_commands


class CasinoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_eco(self):
        return self.bot.cogs.get("EconomyCog")

    # ---------- /slots ----------

    @app_commands.command(name="slots", description="Play the slot machine and gamble your coins!")
    @app_commands.describe(bet="Amount of coins to bet.")
    async def slots(self, interaction: discord.Interaction, bet: int):
        if bet <= 0:
            await interaction.response.send_message("❌ You must bet a positive amount.", ephemeral=True)
            return

        eco = await self.get_eco()
        if not eco:
            await interaction.response.send_message("❌ Economy system is currently offline.", ephemeral=True)
            return

        success = await eco.take_coins(interaction.user.id, interaction.guild.id, bet)
        if not success:
            await interaction.response.send_message("❌ You don't have enough coins for this bet!", ephemeral=True)
            return

        emojis = ["🍒", "🍋", "🍉", "🍇", "🔔", "💎"]
        
        # Determine outcome early
        is_jackpot = random.random() < 0.05
        is_win = random.random() < 0.35

        if is_jackpot:
            result = [random.choice(emojis)] * 3
            multiplier = 5
        elif is_win:
            common = random.choice(emojis)
            result = [common, common, random.choice(emojis)]
            random.shuffle(result)
            multiplier = 2
        else:
            result = [random.choice(emojis) for _ in range(3)]
            if result[0] == result[1] == result[2]:
                result[2] = random.choice([e for e in emojis if e != result[0]])
            multiplier = 0

        winnings = bet * multiplier

        # Animation
        embed = discord.Embed(title="🎰 Slot Machine", color=discord.Color.gold())
        embed.description = "Spinning...\n\n🔲 | 🔲 | 🔲"
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        await asyncio.sleep(1)
        embed.description = f"Spinning...\n\n{result[0]} | 🔲 | 🔲"
        await msg.edit(embed=embed)

        await asyncio.sleep(1)
        embed.description = f"Spinning...\n\n{result[0]} | {result[1]} | 🔲"
        await msg.edit(embed=embed)

        await asyncio.sleep(1)
        embed.description = f"**{result[0]} | {result[1]} | {result[2]}**"
        
        if multiplier > 0:
            await eco.add_coins(interaction.user.id, interaction.guild.id, winnings)
            embed.description += f"\n\n🎉 **YOU WON!** You gain **{winnings:,} 🪙**!"
            embed.color = discord.Color.green()
        else:
            embed.description += f"\n\n❌ **YOU LOST.** You lost **{bet:,} 🪙**."
            embed.color = discord.Color.red()

        await msg.edit(embed=embed)

    # ---------- /blackjack ----------

    @app_commands.command(name="blackjack", description="Play a hand of blackjack against the dealer.")
    @app_commands.describe(bet="Amount of coins to bet.")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        if bet <= 0:
            await interaction.response.send_message("❌ You must bet a positive amount.", ephemeral=True)
            return

        eco = await self.get_eco()
        if not eco:
            await interaction.response.send_message("❌ Economy offline.", ephemeral=True)
            return

        success = await eco.take_coins(interaction.user.id, interaction.guild.id, bet)
        if not success:
            await interaction.response.send_message("❌ Not enough coins!", ephemeral=True)
            return

        deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4
        random.shuffle(deck)

        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        def hand_value(hand):
            val = sum(hand)
            aces = hand.count(11)
            while val > 21 and aces:
                val -= 10
                aces -= 1
            return val

        class BlackjackView(discord.ui.View):
            def __init__(self, c_eco):
                super().__init__(timeout=60)
                self.eco = c_eco
                self.game_over = False

            async def end_game(self, e_interaction, msg, status, color):
                self.game_over = True
                for item in self.children:
                    item.disabled = True
                
                pval = hand_value(player_hand)
                dval = hand_value(dealer_hand)
                
                desc = f"**Your Hand:** {player_hand} (Total: {pval})\n"
                desc += f"**Dealer's Hand:** {dealer_hand} (Total: {dval})\n\n"
                
                if status == "win":
                    desc += f"🎉 **You Win!** +{bet*2:,} 🪙"
                    await self.eco.add_coins(interaction.user.id, interaction.guild.id, bet * 2)
                elif status == "push":
                    desc += f"🤝 **Push (Tie)!** Bet returned."
                    await self.eco.add_coins(interaction.user.id, interaction.guild.id, bet)
                else:
                    desc += f"❌ **You Lose!** -{bet:,} 🪙"

                em = discord.Embed(title="🃏 Blackjack", description=desc, color=color)
                await e_interaction.response.edit_message(embed=em, view=self)

            @discord.ui.button(label="Hit", style=discord.ButtonStyle.green)
            async def hit(self, idx: discord.Interaction, button: discord.ui.Button):
                if idx.user.id != interaction.user.id:
                    return
                player_hand.append(deck.pop())
                if hand_value(player_hand) > 21:
                    await self.end_game(idx, msg, "lose", discord.Color.red())
                else:
                    em = discord.Embed(title="🃏 Blackjack", color=discord.Color.blurple())
                    em.description = f"**Your Hand:** {player_hand} (Total: {hand_value(player_hand)})\n**Dealer:** [{dealer_hand[0]}, ?]"
                    await idx.response.edit_message(embed=em, view=self)

            @discord.ui.button(label="Stand", style=discord.ButtonStyle.red)
            async def stand(self, idx: discord.Interaction, button: discord.ui.Button):
                if idx.user.id != interaction.user.id:
                    return
                while hand_value(dealer_hand) < 17:
                    dealer_hand.append(deck.pop())
                
                pval = hand_value(player_hand)
                dval = hand_value(dealer_hand)
                
                if dval > 21 or pval > dval:
                    await self.end_game(idx, msg, "win", discord.Color.green())
                elif pval == dval:
                    await self.end_game(idx, msg, "push", discord.Color.greyple())
                else:
                    await self.end_game(idx, msg, "lose", discord.Color.red())

        view = BlackjackView(eco)
        embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.blurple())
        
        pval = hand_value(player_hand)
        if pval == 21:
            # Blackjack!
            embed.description = f"**Your Hand:** {player_hand} (Total: 21)\n**Dealer:** {dealer_hand}"
            embed.description += f"\n\n🎉 **BLACKJACK!** You win **{int(bet * 2.5):,} 🪙**!"
            embed.color = discord.Color.gold()
            await eco.add_coins(interaction.user.id, interaction.guild.id, int(bet * 2.5))
            await interaction.response.send_message(embed=embed)
            return

        embed.description = f"**Your Hand:** {player_hand} (Total: {pval})\n**Dealer:** [{dealer_hand[0]}, ?]"
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()

    # ---------- /roulette ----------

    @app_commands.command(name="roulette", description="Bet on Red, Black, or Green in roulette.")
    @app_commands.describe(bet="Amount to bet.", choice="Red (2x), Black (2x), or Green (14x).")
    @app_commands.choices(choice=[
        app_commands.Choice(name="🔴 Red", value="red"),
        app_commands.Choice(name="⚫ Black", value="black"),
        app_commands.Choice(name="🟢 Green", value="green")
    ])
    async def roulette(self, interaction: discord.Interaction, bet: int, choice: str):
        if bet <= 0:
            await interaction.response.send_message("❌ Must bet a positive amount.", ephemeral=True)
            return

        eco = await self.get_eco()
        if not eco: return

        if not await eco.take_coins(interaction.user.id, interaction.guild.id, bet):
            await interaction.response.send_message("❌ Not enough coins!", ephemeral=True)
            return

        roll = random.random()
        if roll < 0.05:
            result, color, emoji = "green", discord.Color.green(), "🟢"
            multiplier = 14
        elif roll < 0.525:
            result, color, emoji = "red", discord.Color.red(), "🔴"
            multiplier = 2
        else:
            result, color, emoji = "black", discord.Color.dark_theme(), "⚫"
            multiplier = 2

        embed = discord.Embed(title="🎡 Roulette", description="The wheel is spinning...", color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        await asyncio.sleep(2)

        desc = f"The ball landed on {emoji} **{result.upper()}**!\n\n"
        if choice == result:
            winnings = bet * multiplier
            await eco.add_coins(interaction.user.id, interaction.guild.id, winnings)
            desc += f"🎉 **YOU WON!** You gain **{winnings:,} 🪙**!"
            embed.color = discord.Color.green()
        else:
            desc += f"❌ **YOU LOST.** You lost **{bet:,} 🪙**."
            embed.color = discord.Color.red()

        embed.description = desc
        await msg.edit(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CasinoCog(bot))
