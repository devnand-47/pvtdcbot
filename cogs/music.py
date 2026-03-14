# cogs/music.py
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import yt_dlp

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Unknown Title")
        self.url = data.get("webpage_url", "")
        self.thumbnail = data.get("thumbnail", "")
        self.duration = data.get("duration", 0)

    @classmethod
    async def from_query(cls, query: str, *, loop=None, volume=0.5):
        loop = loop or asyncio.get_event_loop()
        ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        if "entries" in data:
            data = data["entries"][0]

        url = data.get("url")
        if not url:
            raise ValueError("Could not extract stream URL.")

        return cls(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS), data=data, volume=volume)


class MusicQueue:
    def __init__(self):
        self.queue: list[dict] = []
        self.current: Optional[YTDLSource] = None
        self.volume: float = 0.5

    def add(self, query: str):
        self.queue.append({"query": query})

    def next(self):
        if self.queue:
            return self.queue.pop(0)
        return None

    def clear(self):
        self.queue.clear()
        self.current = None


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guilds_music: dict[int, MusicQueue] = {}

    def get_queue(self, guild_id: int) -> MusicQueue:
        if guild_id not in self.guilds_music:
            self.guilds_music[guild_id] = MusicQueue()
        return self.guilds_music[guild_id]

    def play_next(self, guild: discord.Guild):
        queue = self.get_queue(guild.id)
        vc = guild.voice_client

        if not vc or not vc.is_connected():
            return

        next_item = queue.next()
        if not next_item:
            queue.current = None
            return

        async def _play():
            try:
                source = await YTDLSource.from_query(next_item["query"], loop=self.bot.loop, volume=queue.volume)
                queue.current = source
                vc.play(source, after=lambda e: self.play_next(guild))
            except Exception as e:
                print(f"[Music] Error playing next: {e}")

        asyncio.run_coroutine_threadsafe(_play(), self.bot.loop)

    # ---------- /connect ----------

    @app_commands.command(name="connect", description="Connect the bot to a voice channel.")
    @app_commands.describe(channel="Voice channel to connect to (optional - defaults to your current channel).")
    async def connect(self, interaction: discord.Interaction, channel: Optional[discord.VoiceChannel] = None):
        if not channel:
            if isinstance(interaction.user, discord.Member) and interaction.user.voice:
                channel = interaction.user.voice.channel
            else:
                await interaction.response.send_message("❌ You're not in a voice channel! Specify one or join one first.", ephemeral=True)
                return

        vc = interaction.guild.voice_client
        try:
            if vc:
                await vc.move_to(channel)
            else:
                await channel.connect()
            await interaction.response.send_message(f"🔊 Connected to **{channel.name}**!", ephemeral=False)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to join that channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    # ---------- /disconnect ----------

    @app_commands.command(name="disconnect", description="Disconnect the bot from the voice channel.")
    async def disconnect(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("❌ I'm not in a voice channel.", ephemeral=True)
            return

        queue = self.get_queue(interaction.guild.id)
        queue.clear()
        if vc.is_playing():
            vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("👋 Disconnected from voice channel.", ephemeral=False)

    # ---------- /play ----------

    @app_commands.command(name="play", description="Play a song from YouTube (URL or search term).")
    @app_commands.describe(query="YouTube URL or search term (e.g. 'Lo-fi hip hop')")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        vc = interaction.guild.voice_client
        if not vc:
            # Auto-connect to user's channel
            if isinstance(interaction.user, discord.Member) and interaction.user.voice:
                vc = await interaction.user.voice.channel.connect()
            else:
                await interaction.followup.send("❌ You need to be in a voice channel first, or use `/connect`.")
                return

        queue = self.get_queue(interaction.guild.id)

        if vc.is_playing() or vc.is_paused():
            # Add to queue
            queue.add(query)
            await interaction.followup.send(f"📋 Added to queue: `{query}` (position #{len(queue.queue)})")
            return

        # Play immediately
        try:
            source = await YTDLSource.from_query(query, loop=self.bot.loop, volume=queue.volume)
            queue.current = source
            vc.play(source, after=lambda e: self.play_next(interaction.guild))

            embed = discord.Embed(
                title="🎵 Now Playing",
                description=f"**[{source.title}]({source.url})**",
                color=discord.Color.from_rgb(114, 137, 218)
            )
            if source.thumbnail:
                embed.set_thumbnail(url=source.thumbnail)
            duration_str = f"{source.duration // 60}:{source.duration % 60:02d}" if source.duration else "Live"
            embed.add_field(name="Duration", value=duration_str, inline=True)
            embed.add_field(name="Requested by", value=interaction.user.display_name, inline=True)
            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"❌ Error playing audio: `{e}`")

    # ---------- /skip ----------

    @app_commands.command(name="skip", description="Skip the current song.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=True)
            return

        vc.stop()
        await interaction.response.send_message("⏭️ Skipped!")

    # ---------- /stop ----------

    @app_commands.command(name="stop", description="Stop music and clear the queue.")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            self.get_queue(interaction.guild.id).clear()
            vc.stop()
        await interaction.response.send_message("⏹️ Music stopped and queue cleared.")

    # ---------- /queue ----------

    @app_commands.command(name="queue", description="View the current music queue.")
    async def queue_view(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild.id)
        embed = discord.Embed(title="🎶 Music Queue", color=discord.Color.blurple())

        if queue.current:
            embed.add_field(name="▶️ Now Playing", value=f"`{queue.current.title}`", inline=False)

        if queue.queue:
            queue_text = "\n".join([f"`{i+1}.` {item['query']}" for i, item in enumerate(queue.queue)])
            embed.add_field(name="📋 Up Next", value=queue_text[:1024], inline=False)
        else:
            embed.add_field(name="📋 Up Next", value="*The queue is empty.*", inline=False)

        await interaction.response.send_message(embed=embed)

    # ---------- /volume ----------

    @app_commands.command(name="volume", description="Set the music playback volume (0-100).")
    @app_commands.describe(level="Volume level from 0 to 100.")
    async def volume(self, interaction: discord.Interaction, level: int):
        if not 0 <= level <= 100:
            await interaction.response.send_message("❌ Volume must be between 0 and 100.", ephemeral=True)
            return

        queue = self.get_queue(interaction.guild.id)
        queue.volume = level / 100

        vc = interaction.guild.voice_client
        if vc and vc.source:
            vc.source.volume = queue.volume

        await interaction.response.send_message(f"🔊 Volume set to **{level}%**")

    # ---------- /pause ----------

    @app_commands.command(name="pause", description="Pause/resume the current song.")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("❌ Not in a voice channel.", ephemeral=True)
            return

        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Paused.")
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed.")
        else:
            await interaction.response.send_message("❌ Nothing is playing.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
