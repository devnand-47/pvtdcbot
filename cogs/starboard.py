# cogs/starboard.py
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


class StarboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_config(self, guild_id: int):
        cur = await self.bot.db.execute(
            "SELECT channel_id, threshold FROM starboard_config WHERE guild_id=?", (guild_id,)
        )
        return await cur.fetchone()

    async def get_existing(self, original_msg_id: int):
        cur = await self.bot.db.execute(
            "SELECT starboard_msg_id FROM starboard_posts WHERE original_msg_id=?", (original_msg_id,)
        )
        return await cur.fetchone()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != "⭐":
            return
        cfg = await self.get_config(payload.guild_id)
        if not cfg:
            return
        chan_id, threshold = cfg
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            msg = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        # Count ⭐ reactions
        star_count = 0
        for r in msg.reactions:
            if str(r.emoji) == "⭐":
                star_count = r.count
                break

        if star_count < threshold:
            return

        sb_channel = guild.get_channel(chan_id)
        if not isinstance(sb_channel, discord.TextChannel):
            return

        # Already on starboard?
        existing = await self.get_existing(msg.id)

        embed = discord.Embed(
            description=msg.content or "*[No text content]*",
            color=discord.Color.gold(),
            timestamp=msg.created_at
        )
        embed.set_author(name=msg.author.display_name, icon_url=msg.author.display_avatar.url)
        embed.add_field(name="Source", value=f"[Jump to message]({msg.jump_url})", inline=True)
        embed.add_field(name="Channel", value=channel.mention, inline=True)

        if msg.attachments:
            embed.set_image(url=msg.attachments[0].url)

        content = f"⭐ **{star_count}** — {channel.mention}"

        if existing:
            # Update existing starboard message
            try:
                sb_msg = await sb_channel.fetch_message(existing[0])
                await sb_msg.edit(content=content, embed=embed)
            except Exception:
                pass
        else:
            sb_msg = await sb_channel.send(content=content, embed=embed)
            await self.bot.db.execute(
                "INSERT INTO starboard_posts (original_msg_id, starboard_msg_id, guild_id) VALUES (?,?,?)",
                (msg.id, sb_msg.id, guild.id)
            )
            await self.bot.db.commit()

    @app_commands.command(name="starboard_setup", description="Set up the starboard channel.")
    @is_admin()
    @app_commands.describe(channel="Channel for starred messages.", threshold="Stars needed (default 3).")
    async def starboard_setup(self, interaction: discord.Interaction, channel: discord.TextChannel, threshold: int = 3):
        await self.bot.db.execute(
            """INSERT INTO starboard_config (guild_id, channel_id, threshold) VALUES (?,?,?)
               ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, threshold=excluded.threshold""",
            (interaction.guild.id, channel.id, threshold)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(
            f"⭐ Starboard set to {channel.mention} with **{threshold} stars** threshold!", ephemeral=True
        )

    @app_commands.command(name="starboard_remove", description="Disable the starboard.")
    @is_admin()
    async def starboard_remove(self, interaction: discord.Interaction):
        await self.bot.db.execute("DELETE FROM starboard_config WHERE guild_id=?", (interaction.guild.id,))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Starboard disabled.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StarboardCog(bot))
