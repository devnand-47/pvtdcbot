# cogs/afk.py

import discord
from discord.ext import commands
import asyncio

class AFKCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Dictionary to keep track of running AFK tasks: {user_id: asyncio.Task}
        self.afk_tasks = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot or not member.voice or not member.voice.channel:
                    continue
                is_afk = member.voice.self_mute and member.voice.self_deaf or member.voice.mute and member.voice.deaf
                if is_afk:
                    # Check DB
                    if hasattr(self.bot, "db") and self.bot.db:
                        try:
                            cursor = await self.bot.db.execute("SELECT afk_move_enabled FROM guild_settings WHERE guild_id = ?", (guild.id,))
                            row = await cursor.fetchone()
                            if not row or not row[0]:
                                continue
                        except Exception:
                            continue
                    if member.id not in self.afk_tasks:
                        self.afk_tasks[member.id] = self.bot.loop.create_task(self.afk_timer(member))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        # Check if they are deaf/muted
        is_afk = after.self_mute and after.self_deaf or after.mute and after.deaf

        if after.channel is not None and is_afk:
            # Check dashboard settings first
            if hasattr(self.bot, "db") and self.bot.db:
                cursor = await self.bot.db.execute("SELECT afk_move_enabled FROM guild_settings WHERE guild_id = ?", (member.guild.id,))
                row = await cursor.fetchone()
                if not row or not row[0]: # Not enabled
                    return

            # They became AFK, start a timer if not already running
            if member.id not in self.afk_tasks:
                self.afk_tasks[member.id] = self.bot.loop.create_task(self.afk_timer(member))
        else:
            # They are no longer AFK (unmuted, undeafened, or left VC), cancel timer
            if member.id in self.afk_tasks:
                self.afk_tasks[member.id].cancel()
                del self.afk_tasks[member.id]

    async def afk_timer(self, member: discord.Member):
        try:
            # Wait for 300 seconds (5 minutes)
            await asyncio.sleep(300)

            # If the task wasn't cancelled, check if they are still connected and deafened
            guild = member.guild
            if member.voice and member.voice.channel:
                is_afk = member.voice.self_mute and member.voice.self_deaf or member.voice.mute and member.voice.deaf
                
                if is_afk:
                    # Move them to the AFK channel
                    afk_channel = guild.afk_channel
                    if afk_channel:
                        # Don't move if they are already in the AFK channel
                        if member.voice.channel.id != afk_channel.id:
                            try:
                                await member.move_to(afk_channel, reason="AFK Auto-Move")
                                try:
                                    await member.send(f"💤 You were automatically moved to **{afk_channel.name}** in **{guild.name}** because you were muted and deafened for 5 minutes.")
                                except discord.Forbidden:
                                    pass
                            except discord.Forbidden:
                                print(f"[{guild.name}] Forbidden to move {member.display_name} to AFK. Missing 'Move Members' perm.")
                            except discord.HTTPException as e:
                                print(f"[{guild.name}] HTTP error moving {member.display_name}: {e}")
                    else:
                        print(f"[{guild.name}] No AFK channel set in Server Settings! Could not auto-move {member.display_name}.")
                else:
                    print(f"[{guild.name}] {member.display_name} is no longer fully deafened. Skipping move.")

        except asyncio.CancelledError:
            pass
        finally:
            # Clean up the task
            if member.id in self.afk_tasks:
                del self.afk_tasks[member.id]

async def setup(bot: commands.Bot):
    await bot.add_cog(AFKCog(bot))
