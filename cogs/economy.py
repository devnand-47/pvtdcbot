# cogs/economy.py
import time
import random
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
from config import ADMIN_ROLE_IDS

DAILY_MIN = 100
DAILY_MAX = 250
DAILY_COOLDOWN = 86400  # 24h
MSG_COINS_MIN = 5
MSG_COINS_MAX = 15
MSG_COOLDOWN = 60  # 1 min per user to earn from messages
_last_msg_earn: dict[int, float] = {}


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


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_balance(self, user_id: int, guild_id: int) -> int:
        cur = await self.bot.db.execute(
            "SELECT coins FROM economy WHERE user_id=? AND guild_id=?", (user_id, guild_id)
        )
        row = await cur.fetchone()
        return row[0] if row else 0

    async def add_coins(self, user_id: int, guild_id: int, amount: int):
        await self.bot.db.execute(
            """INSERT INTO economy (user_id, guild_id, coins, last_daily) VALUES (?,?,?,0)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET coins = coins + ?""",
            (user_id, guild_id, amount, amount)
        )
        await self.bot.db.commit()

    async def take_coins(self, user_id: int, guild_id: int, amount: int) -> bool:
        bal = await self.get_balance(user_id, guild_id)
        if bal < amount:
            return False
        await self.bot.db.execute(
            "UPDATE economy SET coins = coins - ? WHERE user_id=? AND guild_id=?",
            (amount, user_id, guild_id)
        )
        await self.bot.db.commit()
        return True

    # ---------- Passive earning on message ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        key = (message.author.id, message.guild.id)
        now = time.time()
        if now - _last_msg_earn.get(key, 0) < MSG_COOLDOWN:
            return
        _last_msg_earn[key] = now
        earned = random.randint(MSG_COINS_MIN, MSG_COINS_MAX)
        await self.add_coins(message.author.id, message.guild.id, earned)

    # ---------- /daily ----------

    @app_commands.command(name="daily", description="Claim your daily coin reward.")
    async def daily(self, interaction: discord.Interaction):
        now = int(time.time())
        cur = await self.bot.db.execute(
            "SELECT last_daily FROM economy WHERE user_id=? AND guild_id=?",
            (interaction.user.id, interaction.guild.id)
        )
        row = await cur.fetchone()
        last = row[0] if row else 0
        if now - last < DAILY_COOLDOWN:
            remaining = DAILY_COOLDOWN - (now - last)
            h, m = divmod(remaining // 60, 60)
            await interaction.response.send_message(
                f"⏳ You already claimed today's reward! Come back in **{h}h {m}m**.", ephemeral=True
            )
            return

        amount = random.randint(DAILY_MIN, DAILY_MAX)
        await self.bot.db.execute(
            """INSERT INTO economy (user_id, guild_id, coins, last_daily) VALUES (?,?,?,?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET coins = coins + ?, last_daily = ?""",
            (interaction.user.id, interaction.guild.id, amount, now, amount, now)
        )
        await self.bot.db.commit()
        bal = await self.get_balance(interaction.user.id, interaction.guild.id)
        embed = discord.Embed(
            title="💰 Daily Reward Claimed!",
            description=f"You received **{amount:,} 🪙 coins**!\nNew balance: **{bal:,} 🪙**",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed)

    # ---------- /balance ----------

    @app_commands.command(name="balance", description="Check your coin balance.")
    @app_commands.describe(member="User to check (optional).")
    async def balance(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        bal = await self.get_balance(target.id, interaction.guild.id)
        embed = discord.Embed(
            title=f"💰 {target.display_name}'s Balance",
            description=f"**{bal:,} 🪙 coins**",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    # ---------- /give ----------

    @app_commands.command(name="give", description="Give coins to another member.")
    @app_commands.describe(member="Who to give coins to.", amount="How many coins.")
    async def give(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        if member.bot or member.id == interaction.user.id:
            await interaction.response.send_message("❌ Invalid target.", ephemeral=True)
            return
        success = await self.take_coins(interaction.user.id, interaction.guild.id, amount)
        if not success:
            await interaction.response.send_message("❌ You don't have enough coins!", ephemeral=True)
            return
        await self.add_coins(member.id, interaction.guild.id, amount)
        await interaction.response.send_message(
            f"✅ Sent **{amount:,} 🪙 coins** to {member.mention}!"
        )

    # ---------- /leaderboard_coins ----------

    @app_commands.command(name="leaderboard_coins", description="View the richest members.")
    async def leaderboard_coins(self, interaction: discord.Interaction):
        cur = await self.bot.db.execute(
            "SELECT user_id, coins FROM economy WHERE guild_id=? ORDER BY coins DESC LIMIT 10",
            (interaction.guild.id,)
        )
        rows = await cur.fetchall()
        embed = discord.Embed(title="💰 Coin Leaderboard", color=discord.Color.gold())
        medals = ["🥇", "🥈", "🥉"]
        desc = ""
        for i, (uid, coins) in enumerate(rows):
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            desc += f"{medal} **{name}** — {coins:,} 🪙\n"
        embed.description = desc or "No data yet."
        await interaction.response.send_message(embed=embed)

    # ---------- /shop ----------

    @app_commands.command(name="shop", description="Browse the server shop.")
    async def shop(self, interaction: discord.Interaction):
        cur = await self.bot.db.execute(
            "SELECT id, name, price, role_id FROM economy_shop WHERE guild_id=? ORDER BY price",
            (interaction.guild.id,)
        )
        rows = await cur.fetchall()
        embed = discord.Embed(title="🛒 Server Shop", color=discord.Color.blurple())
        if not rows:
            embed.description = "The shop is empty! Admins can add items with `/shop_add`."
        else:
            for sid, name, price, role_id in rows:
                role_str = f"<@&{role_id}>" if role_id else "None"
                embed.add_field(name=f"`{name}` — {price:,} 🪙", value=f"Reward: {role_str}", inline=False)
        await interaction.response.send_message(embed=embed)

    # ---------- /buy ----------

    @app_commands.command(name="buy", description="Buy an item from the shop.")
    @app_commands.describe(item="Name of the item to buy.")
    async def buy(self, interaction: discord.Interaction, item: str):
        cur = await self.bot.db.execute(
            "SELECT id, price, role_id FROM economy_shop WHERE guild_id=? AND LOWER(name)=LOWER(?)",
            (interaction.guild.id, item)
        )
        row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(f"❌ Item **{item}** not found in shop.", ephemeral=True)
            return
        sid, price, role_id = row
        success = await self.take_coins(interaction.user.id, interaction.guild.id, price)
        if not success:
            await interaction.response.send_message(f"❌ Not enough coins! Need **{price:,} 🪙**.", ephemeral=True)
            return
        if role_id and isinstance(interaction.user, discord.Member):
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await interaction.user.add_roles(role, reason=f"Bought from shop: {item}")
                except discord.Forbidden:
                    pass
        await interaction.response.send_message(f"✅ Purchased **{item}** for **{price:,} 🪙**!")

    # ---------- /shop_add ----------

    @app_commands.command(name="shop_add", description="Add an item to the shop. (Admin)")
    @is_admin()
    @app_commands.describe(name="Item name.", price="Coin price.", role="Role to grant on purchase (optional).")
    async def shop_add(self, interaction: discord.Interaction, name: str, price: int, role: Optional[discord.Role] = None):
        role_id = role.id if role else None
        await self.bot.db.execute(
            "INSERT INTO economy_shop (guild_id, name, price, role_id) VALUES (?,?,?,?)",
            (interaction.guild.id, name, price, role_id)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Added **{name}** to shop for **{price:,} 🪙**.", ephemeral=True)

    # ---------- /shop_remove ----------

    @app_commands.command(name="shop_remove", description="Remove an item from the shop. (Admin)")
    @is_admin()
    @app_commands.describe(name="Item name to remove.")
    async def shop_remove(self, interaction: discord.Interaction, name: str):
        await self.bot.db.execute(
            "DELETE FROM economy_shop WHERE guild_id=? AND LOWER(name)=LOWER(?)",
            (interaction.guild.id, name)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"🗑️ Removed **{name}** from the shop.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyCog(bot))
