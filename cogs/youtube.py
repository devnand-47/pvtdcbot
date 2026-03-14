# cogs/youtube.py

import discord
from discord.ext import commands, tasks
from discord import app_commands
import httpx
import xml.etree.ElementTree as ET
import logging

log = logging.getLogger("UltimateBot.YouTube")

class YouTubeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.youtube_loop.start()

    def cog_unload(self):
        self.youtube_loop.cancel()

    @tasks.loop(minutes=10)
    async def youtube_loop(self):
        if not hasattr(self.bot, "db") or not self.bot.db:
            return

        try:
            # Fetch all configured YouTube channels
            cursor = await self.bot.db.execute("SELECT id, guild_id, channel_id, youtube_channel_id, last_video_id FROM youtube_notifications")
            rows = await cursor.fetchall()

            if not rows:
                return

            async with httpx.AsyncClient() as client:
                for row in rows:
                    config_id, guild_id, discord_channel_id, yt_channel_id, last_video_id = row
                    
                    try:
                        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={yt_channel_id}"
                        response = await client.get(url, timeout=10.0)
                        
                        if response.status_code == 200:
                            # Parse XML feed
                            root = ET.fromstring(response.text)
                            
                            # xml namespace
                            ns = {'yt': 'http://www.youtube.com/xml/schemas/2015',
                                  'atom': 'http://www.w3.org/2005/Atom'}
                            
                            author_name = root.find("atom:author/atom:name", ns)
                            channel_name = author_name.text if author_name is not None else "YouTube Channel"
                            
                            latest_entry = root.find("atom:entry", ns)
                            if latest_entry is not None:
                                video_id_elem = latest_entry.find("yt:videoId", ns)
                                title_elem = latest_entry.find("atom:title", ns)
                                link_elem = latest_entry.find("atom:link", ns)
                                
                                if video_id_elem is not None and title_elem is not None and link_elem is not None:
                                    video_id = video_id_elem.text
                                    title = title_elem.text
                                    video_url = link_elem.attrib['href']
                                    
                                    # Is it a new video?
                                    if video_id != last_video_id:
                                        log.info(f"[YouTube] New video detected: {title} by {channel_name} ({video_id})")
                                        
                                        # Update DB
                                        await self.bot.db.execute("UPDATE youtube_notifications SET last_video_id = ? WHERE id = ?", (video_id, config_id))
                                        await self.bot.db.commit()
                                        
                                        # We skip notifying if this was the very first check (last_video_id was None) to avoid pinging historical videos
                                        if last_video_id is not None:
                                            channel = self.bot.get_channel(discord_channel_id)
                                            if channel:
                                                await channel.send(
                                                    content=f"Hey! **{channel_name}** just posted a new video/stream!\n\n**{title}**\n{video_url}"
                                                )
                                                
                    except Exception as e:
                        log.error(f"[YouTube] Failed to check feed for {yt_channel_id}: {e}")
                        
        except Exception as e:
            log.error(f"[YouTube] Background task error: {e}")

    @youtube_loop.before_loop
    async def before_youtube_loop(self):
        await self.bot.wait_until_ready()

    youtube_group = app_commands.Group(name="youtube", description="Manage YouTube live/upload notifications", default_permissions=discord.Permissions(manage_guild=True))

    @youtube_group.command(name="add", description="Add a YouTube channel for new upload notifications")
    @app_commands.describe(youtube_channel_id="The ID of the YouTube channel (e.g., UC_x5XG1OV2P6uZZ5FSM9Ttw)", target_channel="The Discord channel to send notifications to")
    async def yt_add_slash(self, interaction: discord.Interaction, youtube_channel_id: str, target_channel: discord.TextChannel):
        if not hasattr(self.bot, "db") or not self.bot.db:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        # Simple verification that the ID format looks somewhat okay (not a URL)
        if "youtube.com" in youtube_channel_id or "youtu.be" in youtube_channel_id:
            await interaction.response.send_message("❌ Please provide the YouTube **Channel ID** (starts with UC...), not the URL.\nYou can use sites like *commentpicker.com/youtube-channel-id.php* to find it.", ephemeral=True)
            return

        cursor = await self.bot.db.execute("SELECT id FROM youtube_notifications WHERE guild_id = ? AND youtube_channel_id = ?", (interaction.guild.id, youtube_channel_id))
        if await cursor.fetchone():
            await interaction.response.send_message("❌ That YouTube channel is already being tracked in this server!", ephemeral=True)
            return
            
        await self.bot.db.execute(
            "INSERT INTO youtube_notifications (guild_id, channel_id, youtube_channel_id, last_video_id) VALUES (?, ?, ?, NULL)",
            (interaction.guild.id, target_channel.id, youtube_channel_id)
        )
        await self.bot.db.commit()
        
        await interaction.response.send_message(f"✅ Successfully added YouTube channel `{youtube_channel_id}`! Notifications will be sent in {target_channel.mention}.")

    @youtube_group.command(name="remove", description="Stop tracking a YouTube channel")
    @app_commands.describe(youtube_channel_id="The ID of the YouTube channel you want to stop tracking")
    async def yt_remove_slash(self, interaction: discord.Interaction, youtube_channel_id: str):
        if not hasattr(self.bot, "db") or not self.bot.db:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        cursor = await self.bot.db.execute("SELECT id FROM youtube_notifications WHERE guild_id = ? AND youtube_channel_id = ?", (interaction.guild.id, youtube_channel_id))
        row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("❌ That YouTube channel is not currently being tracked.", ephemeral=True)
            return

        await self.bot.db.execute("DELETE FROM youtube_notifications WHERE id = ?", (row[0],))
        await self.bot.db.commit()

        await interaction.response.send_message(f"✅ Stopped tracking YouTube channel `{youtube_channel_id}`.", ephemeral=True)

    @youtube_group.command(name="list", description="List all tracked YouTube channels for this server")
    async def yt_list_slash(self, interaction: discord.Interaction):
        if not hasattr(self.bot, "db") or not self.bot.db:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        cursor = await self.bot.db.execute("SELECT youtube_channel_id, channel_id FROM youtube_notifications WHERE guild_id = ?", (interaction.guild.id,))
        rows = await cursor.fetchall()

        if not rows:
            await interaction.response.send_message("❌ No YouTube channels are being tracked in this server.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📺 Tracked YouTube Channels",
            color=discord.Color.red()
        )
        
        desc = ""
        for (yt_id, chan_id) in rows:
            desc += f"• **ID:** `{yt_id}` -> <#{chan_id}>\n"
            
        embed.description = desc
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeCog(bot))
