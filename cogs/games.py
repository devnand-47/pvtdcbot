# cogs/games.py
import random
import asyncio
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional


class GamesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_guess: dict[int, int] = {}  # channel_id -> answer

    # ---------- /rps ----------

    @app_commands.command(name="rps", description="Play Rock, Paper, Scissors against the bot.")
    @app_commands.describe(choice="Your pick: rock, paper, or scissors.")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Rock 🪨", value="rock"),
        app_commands.Choice(name="Paper 📄", value="paper"),
        app_commands.Choice(name="Scissors ✂️", value="scissors"),
    ])
    async def rps(self, interaction: discord.Interaction, choice: str):
        bot_choice = random.choice(["rock", "paper", "scissors"])
        emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        wins = {"rock": "scissors", "paper": "rock", "scissors": "paper"}

        if choice == bot_choice:
            result, color = "It's a tie! 🤝", discord.Color.greyple()
        elif wins[choice] == bot_choice:
            result, color = "You win! 🎉", discord.Color.green()
        else:
            result, color = "I win! 😎", discord.Color.red()

        embed = discord.Embed(title="🪨 Rock Paper Scissors", color=color)
        embed.add_field(name="You", value=emojis[choice], inline=True)
        embed.add_field(name="Bot", value=emojis[bot_choice], inline=True)
        embed.add_field(name="Result", value=result, inline=False)
        await interaction.response.send_message(embed=embed)

    # ---------- /trivia ----------

    @app_commands.command(name="trivia", description="Answer a random trivia question.")
    async def trivia(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://opentdb.com/api.php?amount=1&type=multiple") as resp:
                    data = await resp.json()
        except Exception:
            await interaction.followup.send("❌ Could not fetch a trivia question. Try again.")
            return

        item = data["results"][0]
        import html
        question = html.unescape(item["question"])
        correct = html.unescape(item["correct_answer"])
        wrong = [html.unescape(w) for w in item["incorrect_answers"]]
        options = [correct] + wrong
        random.shuffle(options)
        labels = ["🇦", "🇧", "🇨", "🇩"]
        correct_idx = options.index(correct)

        desc = "\n".join([f"{labels[i]} {opt}" for i, opt in enumerate(options)])
        embed = discord.Embed(
            title=f"🎓 Trivia — {item['category']}",
            description=f"**{question}**\n\n{desc}",
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Difficulty: {item['difficulty'].title()} • You have 20 seconds!")
        msg = await interaction.followup.send(embed=embed)
        for lbl in labels[:len(options)]:
            await msg.add_reaction(lbl)

        def check(r, u):
            return u.id == interaction.user.id and str(r.emoji) in labels and r.message.id == msg.id

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=20, check=check)
            chosen_idx = labels.index(str(reaction.emoji))
            if chosen_idx == correct_idx:
                await interaction.followup.send(f"✅ Correct! The answer was **{correct}**! 🎉")
            else:
                await interaction.followup.send(f"❌ Wrong! The correct answer was **{correct}**.")
        except asyncio.TimeoutError:
            await interaction.followup.send(f"⏰ Time's up! The answer was **{correct}**.")

    # ---------- /guess ----------

    @app_commands.command(name="guess", description="Guess the number the bot is thinking of (1–100).")
    async def guess(self, interaction: discord.Interaction):
        if interaction.channel_id in self._active_guess:
            await interaction.response.send_message("❌ A guess game is already running in this channel!", ephemeral=True)
            return

        number = random.randint(1, 100)
        self._active_guess[interaction.channel_id] = number

        embed = discord.Embed(
            title="🔢 Guess My Number!",
            description="I'm thinking of a number between **1 and 100**.\nType your guesses in this channel! You have **5 attempts**.",
            color=discord.Color.teal()
        )
        await interaction.response.send_message(embed=embed)

        attempts = 5
        for attempt in range(1, attempts + 1):
            def check(m):
                return m.author.id == interaction.user.id and m.channel.id == interaction.channel_id and m.content.isdigit()
            try:
                msg = await self.bot.wait_for("message", timeout=30, check=check)
                guess = int(msg.content)
                if guess == number:
                    await msg.reply(f"🎉 Correct! The number was **{number}**! Got it in {attempt} attempt(s)!")
                    break
                elif guess < number:
                    await msg.reply(f"📈 Too low! ({attempts - attempt} attempts left)")
                else:
                    await msg.reply(f"📉 Too high! ({attempts - attempt} attempts left)")
                if attempt == attempts:
                    await msg.reply(f"😔 Out of attempts! The number was **{number}**.")
            except asyncio.TimeoutError:
                await interaction.channel.send(f"⏰ Game over! The number was **{number}**.")
                break

        self._active_guess.pop(interaction.channel_id, None)

    # ---------- /coinflip ----------

    @app_commands.command(name="coinflip", description="Flip a coin. Optionally bet coins.")
    @app_commands.describe(bet="Bet amount in coins (optional).", side="heads or tails (optional).")
    @app_commands.choices(side=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails"),
    ])
    async def coinflip(self, interaction: discord.Interaction, bet: Optional[int] = None, side: Optional[str] = None):
        result = random.choice(["heads", "tails"])
        emoji = "🦅" if result == "heads" else "🎯"
        won = (side == result) if side else None

        embed = discord.Embed(
            title=f"{emoji} {result.title()}!",
            color=discord.Color.green() if won else (discord.Color.red() if won is False else discord.Color.blurple())
        )

        if bet and side:
            from cogs.economy import EconomyCog
            eco: EconomyCog = self.bot.cogs.get("EconomyCog")
            if eco:
                if won:
                    await eco.add_coins(interaction.user.id, interaction.guild.id, bet)
                    embed.description = f"You bet **{bet:,} 🪙** on **{side}** and **won**! +{bet:,} 🪙"
                else:
                    success = await eco.take_coins(interaction.user.id, interaction.guild.id, bet)
                    if not success:
                        await interaction.response.send_message("❌ Not enough coins to bet!", ephemeral=True)
                        return
                    embed.description = f"You bet **{bet:,} 🪙** on **{side}** and **lost**. -{bet:,} 🪙"
        elif side:
            embed.description = f"You called **{side}** — {'✅ Correct!' if won else '❌ Wrong!'}"
        else:
            embed.description = "The coin has been flipped!"

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesCog(bot))
