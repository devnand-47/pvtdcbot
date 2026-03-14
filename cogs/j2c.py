# cogs/j2c.py
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


class JoinToCreateCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_master_channel(self, guild_id: int):
        cur = await self.bot.db.execute("SELECT master_channel_id, category_id FROM j2c_config WHERE guild_id=?", (guild_id,))
        return await cur.fetchone()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        # Leaving a channel
        if before.channel:
            # Check if left channel is a J2C temporary channel
            cur = await self.bot.db.execute("SELECT owner_id FROM j2c_channels WHERE channel_id=?", (before.channel.id,))
            row = await cur.fetchone()
            if row:
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete(reason="J2C Auto-Cleanup")
                    except discord.NotFound:
                        pass
                    except discord.Forbidden:
                        pass
                    await self.bot.db.execute("DELETE FROM j2c_channels WHERE channel_id=?", (before.channel.id,))
                    await self.bot.db.commit()

        # Joining a channel
        if after.channel:
            config = await self.get_master_channel(member.guild.id)
            if not config:
                return
            master_id, category_id = config

            if after.channel.id == master_id:
                category = member.guild.get_channel(category_id) if category_id else None
                try:
                    new_channel = await member.guild.create_voice_channel(
                        name=f"🔊 {member.display_name}'s VC",
                        category=category,
                        user_limit=0,
                        reason="Join-to-Create execution"
                    )
                    await member.move_to(new_channel, reason="Moved to new J2C channel")
                    await self.bot.db.execute(
                        "INSERT INTO j2c_channels (channel_id, owner_id) VALUES (?, ?)",
                        (new_channel.id, member.id)
                    )
                    await self.bot.db.commit()
                except discord.Forbidden:
                    # Bot lacks permissions to create or move
                    pass

    # ---------- /j2c_setup ----------

    @app_commands.command(name="j2c_setup", description="Deploy the Join-to-Create master channel.")
    @is_admin()
    async def j2c_setup(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild
        category = await guild.create_category("🎙️ PRIVATE CHANNELS")
        master_ch = await guild.create_voice_channel("➕ Create VC", category=category)

        await self.bot.db.execute(
            """INSERT INTO j2c_config (guild_id, master_channel_id, category_id) VALUES (?,?,?)
               ON CONFLICT(guild_id) DO UPDATE SET master_channel_id=excluded.master_channel_id, category_id=excluded.category_id""",
            (guild.id, master_ch.id, category.id)
        )
        await self.bot.db.commit()
        await interaction.followup.send(f"✅ Join-to-Create system deployed!\nMaster channel: {master_ch.mention}")

    # ---------- /vc_lock & unlock ----------

    @app_commands.command(name="vc_lock", description="Lock your active custom Voice Channel.")
    async def vc_lock(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
            return

        vc = interaction.user.voice.channel
        cur = await self.bot.db.execute("SELECT owner_id FROM j2c_channels WHERE channel_id=?", (vc.id,))
        row = await cur.fetchone()
        
        if not row or row[0] != interaction.user.id:
            await interaction.response.send_message("❌ You do not own this voice channel.", ephemeral=True)
            return

        await vc.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message("🔒 Channel **locked**! Regular members cannot join.")

    @app_commands.command(name="vc_unlock", description="Unlock your active custom Voice Channel.")
    async def vc_unlock(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return
        vc = interaction.user.voice.channel
        cur = await self.bot.db.execute("SELECT owner_id FROM j2c_channels WHERE channel_id=?", (vc.id,))
        row = await cur.fetchone()
        
        if not row or row[0] != interaction.user.id:
            return

        await vc.set_permissions(interaction.guild.default_role, connect=None)
        await interaction.response.send_message("🔓 Channel **unlocked**! Anyone can join.")


async def setup(bot: commands.Bot):
    await bot.add_cog(JoinToCreateCog(bot))
