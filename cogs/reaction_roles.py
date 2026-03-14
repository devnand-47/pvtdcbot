# cogs/reaction_roles.py

import discord
from discord.ext import commands
from discord import app_commands
import json
import sqlite3

class ReactionRoleButton(discord.ui.Button):
    def __init__(self, role_id: int, label: str, emoji: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, emoji=emoji, custom_id=f"rr_{role_id}")
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("❌ This role no longer exists dynamically.", ephemeral=True)
            return

        # Let's toggle the role
        if role in interaction.user.roles:
            try:
                await interaction.user.remove_roles(role, reason="Reaction Role Removed")
                await interaction.response.send_message(f"➖ Removed {role.mention} from your profile.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ I do not have permission to manage this role.", ephemeral=True)
        else:
            try:
                await interaction.user.add_roles(role, reason="Reaction Role Added")
                await interaction.response.send_message(f"➕ Added {role.mention} to your profile.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("❌ I do not have permission to manage this role.", ephemeral=True)

class ReactionRoleView(discord.ui.View):
    def __init__(self, roles_data: list):
        # Timeout None means this view lives forever dynamically.
        super().__init__(timeout=None)
        
        # Max limit of 25 buttons per Discord UI view.
        for idx, rdata in enumerate(roles_data):
            if idx >= 25:
                break
                
            style_str = rdata.get("style", "primary")
            style_map = {
                "primary": discord.ButtonStyle.primary,
                "secondary": discord.ButtonStyle.secondary,
                "success": discord.ButtonStyle.success,
                "danger": discord.ButtonStyle.danger
            }
            btn_style = style_map.get(style_str, discord.ButtonStyle.primary)
            
            self.add_item(ReactionRoleButton(
                role_id=int(rdata["role_id"]),
                label=rdata.get("label", "Role"),
                emoji=rdata.get("emoji"),
                style=btn_style
            ))

class ReactionRolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def load_reaction_role_views(self):
        """Dynamically fetch and attach UI Views to persistence on Bot Startup."""
        if getattr(self.bot, "db", None) is None:
            return

        cursor = await self.bot.db.execute("SELECT message_id, roles_json FROM reaction_role_panels")
        rows = await cursor.fetchall()
        
        for row in rows:
            message_id, roles_json = row
            try:
                roles_data = json.loads(roles_json)
                self.bot.add_view(ReactionRoleView(roles_data), message_id=message_id)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_ready(self):
        # We must load persistent views into memory when the bot boots
        # Wait a tiny bit just in case
        await self.bot.wait_until_ready()
        
        if getattr(self.bot, "db", None):
            await self.bot.db.execute("""
                CREATE TABLE IF NOT EXISTS reaction_role_panels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    message_id INTEGER,
                    roles_json TEXT
                )
            """)
            await self.bot.db.commit()
            await self.load_reaction_role_views()

    @app_commands.command(name="spawn_roles", description="Admin: Spawn a custom Button Role panel.")
    @app_commands.default_permissions(administrator=True)
    async def spawn_roles_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Wait, instead of configuring inside discord, we can configure this via Dashboard!
        # The user will build the panel on the dashboard and then click "Deploy Panel".
        # This slash command will just serve as a manual trigger for developers.
        await interaction.followup.send("⚠️ Please build your Reaction Role panels dynamically via the Web Dashboard, then click Deploy!")

async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRolesCog(bot))
