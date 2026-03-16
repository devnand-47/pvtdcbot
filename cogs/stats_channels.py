# cogs/stats_channels.py
import discord
import asyncio
from discord.ext import commands, tasks
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

class StatsChannelsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.update_stats.start()

    def cog_unload(self):
        self.update_stats.cancel()

    async def get_stat_channels(self, guild_id: int):
        if not self.bot.db:
            return None
        cur = await self.bot.db.execute(
            "SELECT category_id, members_channel, online_channel, boosts_channel FROM stats_channels WHERE guild_id = ?",
            (guild_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        return {"category": row[0], "members": row[1], "online": row[2], "boosts": row[3]}

    async def save_stat_channels(self, guild_id: int, category_id: int, members_id: int, online_id: int, boosts_id: int):
        await self.bot.db.execute(
            """
            INSERT INTO stats_channels (guild_id, category_id, members_channel, online_channel, boosts_channel)
            VALUES (?,?,?,?,?)
            ON CONFLICT(guild_id) DO UPDATE SET
              category_id=excluded.category_id,
              members_channel=excluded.members_channel,
              online_channel=excluded.online_channel,
              boosts_channel=excluded.boosts_channel
            """,
            (guild_id, category_id, members_id, online_id, boosts_id)
        )
        await self.bot.db.commit()

    @tasks.loop(minutes=15)
    async def update_stats(self):
        for guild in self.bot.guilds:
            data = await self.get_stat_channels(guild.id)
            if not data:
                continue
            
            members_channel = guild.get_channel(data["members"])
            online_channel = guild.get_channel(data["online"])
            boosts_channel = guild.get_channel(data["boosts"])

            try:
                # 1. Calculate the new names
                new_members_name = f"👥 Members: {guild.member_count:,}"
                
                online_count = sum(1 for m in guild.members if m.status != discord.Status.offline)
                new_online_name = f"🟢 Online: {online_count:,}"
                
                new_boosts_name = f"💎 Boosts: {guild.premium_subscription_count}"

                # 2. Check if the name actually needs to be changed before editing
                if members_channel and members_channel.name != new_members_name:
                    await members_channel.edit(name=new_members_name)
                    
                if online_channel and online_channel.name != new_online_name:
                    await online_channel.edit(name=new_online_name)
                    
                if boosts_channel and boosts_channel.name != new_boosts_name:
                    await boosts_channel.edit(name=new_boosts_name)

            except Exception as e:
                print(f"[Stats] Error updating channels for {guild.name}: {e}")
            
            # 3. This MUST be outside the try/except block so it pauses for EVERY server!
            await asyncio.sleep(2)

    @update_stats.before_loop
    async def before_update(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="stats_setup", description="Create auto-updating server statistics channels.")
    @is_admin()
    async def stats_setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Check if already set up
        existing = await self.get_stat_channels(guild.id)
        if existing and guild.get_channel(existing["category"]):
            await interaction.followup.send("⚠️ Stats channels are already set up! Use `/stats_remove` first to reset.", ephemeral=True)
            return

        try:
            # Create category
            category = await guild.create_category(
                "📊 SERVER STATS",
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True)
                }
            )

            # Create stat channels (voice channels, can't be typed in)
            members_ch = await guild.create_voice_channel(f"👥 Members: {guild.member_count:,}", category=category)
            online_count = sum(1 for m in guild.members if m.status != discord.Status.offline)
            online_ch = await guild.create_voice_channel(f"🟢 Online: {online_count:,}", category=category)
            boosts_ch = await guild.create_voice_channel(f"💎 Boosts: {guild.premium_subscription_count}", category=category)

            await self.save_stat_channels(guild.id, category.id, members_ch.id, online_ch.id, boosts_ch.id)

            await interaction.followup.send(
                f"✅ Stats channels created in category **{category.name}**!\nThey will update automatically every **15 minutes**.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send("❌ I need **Manage Channels** permission to create stat channels.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @app_commands.command(name="stats_remove", description="Delete the auto-updating server statistics channels.")
    @is_admin()
    async def stats_remove(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        data = await self.get_stat_channels(guild.id)

        if not data:
            await interaction.followup.send("ℹ️ No stats channels are currently configured.", ephemeral=True)
            return

        for ch_id in [data["members"], data["online"], data["boosts"]]:
            ch = guild.get_channel(ch_id)
            if ch:
                try:
                    await ch.delete()
                except Exception:
                    pass

        cat = guild.get_channel(data["category"])
        if cat:
            try:
                await cat.delete()
            except Exception:
                pass

        await self.bot.db.execute("DELETE FROM stats_channels WHERE guild_id = ?", (guild.id,))
        await self.bot.db.commit()
        await interaction.followup.send("✅ Stats channels removed.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(StatsChannelsCog(bot))
