# cogs/counting.py
import discord
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


class CountingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: dict[int, dict] = {}  # guild_id -> {channel_id, current_count, last_user_id}

    async def _get(self, guild_id: int) -> dict | None:
        if guild_id in self._cache:
            return self._cache[guild_id]
        cur = await self.bot.db.execute(
            "SELECT channel_id, current_count, last_user_id FROM counting WHERE guild_id=?", (guild_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        data = {"channel_id": row[0], "count": row[1], "last_user": row[2]}
        self._cache[guild_id] = data
        return data

    async def _save(self, guild_id: int, data: dict):
        self._cache[guild_id] = data
        await self.bot.db.execute(
            """INSERT INTO counting (guild_id, channel_id, current_count, last_user_id) VALUES (?,?,?,?)
               ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, current_count=excluded.current_count, last_user_id=excluded.last_user_id""",
            (guild_id, data["channel_id"], data["count"], data["last_user"])
        )
        await self.bot.db.commit()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        data = await self._get(message.guild.id)
        if not data or message.channel.id != data["channel_id"]:
            return

        content = message.content.strip()
        if not content.isdigit():
            await message.add_reaction("❌")
            await message.channel.send(
                f"❌ {message.author.mention} broke the count! Only numbers allowed. Restarting from **0**..."
            )
            data["count"] = 0
            data["last_user"] = None
            await self._save(message.guild.id, data)
            return

        num = int(content)
        expected = data["count"] + 1

        if data["last_user"] == message.author.id:
            await message.add_reaction("❌")
            await message.channel.send(
                f"❌ {message.author.mention}, you can't count twice in a row! Restarting from **0**..."
            )
            data["count"] = 0
            data["last_user"] = None
            await self._save(message.guild.id, data)
            return

        if num != expected:
            await message.add_reaction("❌")
            await message.channel.send(
                f"❌ {message.author.mention} said **{num}** but the next number was **{expected}**! Restarting from **0**..."
            )
            data["count"] = 0
            data["last_user"] = None
            await self._save(message.guild.id, data)
            return

        # Correct!
        data["count"] = num
        data["last_user"] = message.author.id
        await self._save(message.guild.id, data)
        await message.add_reaction("✅")
        # Milestones
        if num % 100 == 0:
            await message.channel.send(f"🎉 **{num}** — milestone reached! Great counting team! 🔢")

    @app_commands.command(name="counting_setup", description="Set up a counting channel.")
    @is_admin()
    @app_commands.describe(channel="The channel to use for counting.")
    async def counting_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        data = {"channel_id": channel.id, "count": 0, "last_user": None}
        await self._save(interaction.guild.id, data)
        await interaction.response.send_message(
            f"🔢 Counting channel set to {channel.mention}! Start counting from **1**.", ephemeral=True
        )

    @app_commands.command(name="counting_remove", description="Disable the counting channel.")
    @is_admin()
    async def counting_remove(self, interaction: discord.Interaction):
        await self.bot.db.execute("DELETE FROM counting WHERE guild_id=?", (interaction.guild.id,))
        await self.bot.db.commit()
        self._cache.pop(interaction.guild.id, None)
        await interaction.response.send_message("✅ Counting channel disabled.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CountingCog(bot))
