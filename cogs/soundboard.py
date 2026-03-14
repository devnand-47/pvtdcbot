# cogs/soundboard.py
import os
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from config import ADMIN_ROLE_IDS

SOUNDS_DIR = os.path.join("data", "sounds")
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg"}


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


class SoundboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        os.makedirs(SOUNDS_DIR, exist_ok=True)

    def _sound_path(self, guild_id: int, name: str) -> str | None:
        """Returns path to sound file if it exists (tries all supported extensions)."""
        for ext in ALLOWED_EXTENSIONS:
            path = os.path.join(SOUNDS_DIR, str(guild_id), f"{name}{ext}")
            if os.path.exists(path):
                return path
        return None

    def _list_sounds(self, guild_id: int) -> list[str]:
        """Returns a sorted list of available sound names for the guild."""
        guild_dir = os.path.join(SOUNDS_DIR, str(guild_id))
        if not os.path.isdir(guild_dir):
            return []
        names = []
        for f in sorted(os.listdir(guild_dir)):
            name, ext = os.path.splitext(f)
            if ext.lower() in ALLOWED_EXTENSIONS:
                names.append(name)
        return names

    # ---------- /soundboard play ----------

    @app_commands.command(name="soundboard", description="Play a soundboard clip in your voice channel.")
    @app_commands.describe(name="Name of the sound to play.")
    async def soundboard_play(self, interaction: discord.Interaction, name: str):
        # Must be in a voice channel
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message("❌ You need to be in a voice channel to use the soundboard.", ephemeral=True)
            return

        sound_path = self._sound_path(interaction.guild.id, name.lower())
        if not sound_path:
            sounds = self._list_sounds(interaction.guild.id)
            tip = f"\n\n**Available sounds:** {', '.join(f'`{s}`' for s in sounds)}" if sounds else "\n\nNo sounds uploaded yet. Ask an admin to use `/soundboard_add`!"
            await interaction.response.send_message(f"❌ Sound **`{name}`** not found.{tip}", ephemeral=True)
            return

        vc: discord.VoiceClient = interaction.guild.voice_client
        try:
            if vc and vc.channel != interaction.user.voice.channel:
                await vc.move_to(interaction.user.voice.channel)
            elif not vc:
                vc = await interaction.user.voice.channel.connect()
        except discord.Forbidden:
            await interaction.response.send_message("❌ I can't join your voice channel.", ephemeral=True)
            return

        if vc.is_playing():
            vc.stop()

        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(sound_path), volume=0.8)
        vc.play(source)

        await interaction.response.send_message(f"🔊 Playing **{name}**!", ephemeral=False)

    # ---------- /soundboard_add (Admin) ----------

    @app_commands.command(name="soundboard_add", description="Upload a sound clip to the server soundboard. (Admin only)")
    @is_admin()
    @app_commands.describe(
        name="Short name for this sound (no spaces, e.g. 'laser_pew').",
        file="Audio file to upload (.mp3, .wav, or .ogg)."
    )
    async def soundboard_add(self, interaction: discord.Interaction, name: str, file: discord.Attachment):
        await interaction.response.defer(ephemeral=True)

        # Validate name
        safe_name = name.lower().replace(" ", "_")
        _, ext = os.path.splitext(file.filename)
        if ext.lower() not in ALLOWED_EXTENSIONS:
            await interaction.followup.send(f"❌ Unsupported file type `{ext}`. Use `.mp3`, `.wav`, or `.ogg`.", ephemeral=True)
            return

        # Validate file size (max 8MB)
        if file.size > 8 * 1024 * 1024:
            await interaction.followup.send("❌ File too large (max 8MB).", ephemeral=True)
            return

        # Save
        guild_dir = os.path.join(SOUNDS_DIR, str(interaction.guild.id))
        os.makedirs(guild_dir, exist_ok=True)
        save_path = os.path.join(guild_dir, f"{safe_name}{ext.lower()}")

        async with aiohttp.ClientSession() as session:
            async with session.get(file.url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("❌ Failed to download the file.", ephemeral=True)
                    return
                with open(save_path, "wb") as f:
                    f.write(await resp.read())

        await interaction.followup.send(f"✅ Sound **`{safe_name}`** added! Use `/soundboard {safe_name}` to play it.", ephemeral=True)

    # ---------- /soundboard_list ----------

    @app_commands.command(name="soundboard_list", description="List all available soundboard clips.")
    async def soundboard_list(self, interaction: discord.Interaction):
        sounds = self._list_sounds(interaction.guild.id)

        if not sounds:
            await interaction.response.send_message(
                "🔇 No sounds uploaded yet! Admins can add sounds with `/soundboard_add`.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🎵 Soundboard",
            description="\n".join([f"• `{s}`" for s in sounds]),
            color=discord.Color.from_rgb(88, 101, 242)
        )
        embed.set_footer(text=f"Use /soundboard <name> to play a sound • {len(sounds)} clip(s) available")
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---------- /soundboard_remove (Admin) ----------

    @app_commands.command(name="soundboard_remove", description="Delete a sound from the soundboard. (Admin only)")
    @is_admin()
    @app_commands.describe(name="Name of the sound to delete.")
    async def soundboard_remove(self, interaction: discord.Interaction, name: str):
        sound_path = self._sound_path(interaction.guild.id, name.lower())
        if not sound_path:
            await interaction.response.send_message(f"❌ Sound **`{name}`** not found.", ephemeral=True)
            return

        os.remove(sound_path)
        await interaction.response.send_message(f"🗑️ Sound **`{name}`** deleted.", ephemeral=True)

    # ---------- /soundboard_stop ----------

    @app_commands.command(name="soundboard_stop", description="Stop the currently playing soundboard clip.")
    async def soundboard_stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏹️ Stopped.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SoundboardCog(bot))
