# cogs/tickets.py

import io
import time
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands


class TicketCloseView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="🔒 Close Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="ticket_close",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Closing ticket in 5 seconds...", ephemeral=False)
        
        guild = interaction.guild
        channel = interaction.channel
        if not guild or not channel or not self.bot.db:
            return

        # Fetch log channel settings
        cursor = await self.bot.db.execute(
            "SELECT ticket_log_channel_id FROM guild_settings WHERE guild_id = ?",
            (guild.id,)
        )
        row = await cursor.fetchone()
        
        if row and row[0]:
            log_channel = guild.get_channel(row[0])
            if log_channel:
                # Generate transcript
                transcript = f"Transcript for {channel.name}\n"
                transcript += f"Closed by: {interaction.user} ({interaction.user.id})\n"
                transcript += "-" * 40 + "\n\n"
                
                messages = []
                # Fetch up to 500 messages
                try:
                    async for msg in channel.history(limit=500, oldest_first=True):
                        messages.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author}: {msg.content}")
                except Exception:
                    pass
                
                transcript += "\n".join(messages)
                
                file = discord.File(io.BytesIO(transcript.encode('utf-8')), filename=f"{channel.name}_transcript.txt")
                
                embed = discord.Embed(
                    title="🎫 Ticket Closed",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Ticket", value=channel.name, inline=True)
                embed.add_field(name="Closed By", value=interaction.user.mention, inline=True)
                
                try:
                    await log_channel.send(embed=embed, file=file)
                except Exception:
                    pass

        import asyncio
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except Exception:
            pass


class TicketOpenView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="🎫 Open Ticket",
        style=discord.ButtonStyle.primary,
        custom_id="ticket_open",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        
        if not guild or not self.bot.db:
            return await interaction.response.send_message("❌ Database error. Try again later.", ephemeral=True)
            
        cursor = await self.bot.db.execute(
            "SELECT ticket_category_id, ticket_role_id FROM guild_settings WHERE guild_id = ?",
            (guild.id,)
        )
        row = await cursor.fetchone()
        
        if not row or not row[0]:
            return await interaction.response.send_message(
                "❌ Tickets are not configured on this server! Admins must configure the Ticket Category on the Dashboard.", 
                ephemeral=True
            )
            
        await interaction.response.defer(ephemeral=True)
        
        category = guild.get_channel(row[0])
        if not category or not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send("❌ Configured Ticket Category is missing or invalid.", ephemeral=True)
            
        # Create base permissions (Invisible to everyone except bot and user)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        }
        
        # Add Staff roles if configured
        import json
        staff_roles = []
        if row[1]:
            try:
                role_ids = json.loads(row[1])
                for r_id in role_ids:
                    r = guild.get_role(int(r_id))
                    if r:
                        staff_roles.append(r)
            except (ValueError, TypeError):
                # Fallback for old single integer DB format
                r = guild.get_role(int(row[1]))
                if r:
                    staff_roles.append(r)

        for staff_role in staff_roles:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
                
        # Create Channel
        try:
            # Prevent dashes and symbols, lowercase channel name
            safe_name = "".join([c.lower() for c in user.name if c.isalnum()])
            channel_name = f"ticket-{safe_name}"
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Discord ID: {user.id}"
            )
        except discord.Forbidden:
            return await interaction.followup.send("❌ I don't have permission to create channels!", ephemeral=True)
            
        # Send Welcome Embed to private channel
        embed = discord.Embed(
            title="🎫 Support Ticket",
            description=f"Welcome {user.mention}!\n\nPlease describe your issue or question in detail, and our support team will be with you shortly.",
            color=discord.Color.from_rgb(0, 255, 255)
        )
        
        ping_msg = user.mention
        for role in staff_roles:
            ping_msg += f" {role.mention}"
            
        await ticket_channel.send(content=ping_msg, embed=embed, view=TicketCloseView(self.bot))
        
        await interaction.followup.send(f"✅ Your ticket has been created: {ticket_channel.mention}", ephemeral=True)


class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # Register persistent views
        self.bot.add_view(TicketOpenView(self.bot))
        self.bot.add_view(TicketCloseView(self.bot))

    @app_commands.command(name="ticket_panel", description="Deploy the Support Ticket Interface Panel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎫 Support Desk",
            description="Need help? Click the button below to open a private ticket with our support staff.",
            color=discord.Color.from_rgb(0, 255, 255)
        )
        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
            
        await interaction.channel.send(embed=embed, view=TicketOpenView(self.bot))
        await interaction.response.send_message("✅ Ticket panel deployed.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCog(bot))
