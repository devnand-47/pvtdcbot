# cogs/welcome.py

import discord
from discord.ext import commands
from discord import app_commands

from config import (
    GUILD_ID,
    RULES_CHANNEL_ID,
    WELCOME_CHANNEL_ID,
    ADMIN_ROLE_IDS,
    VERIFICATION_CHANNEL_ID,   # NEW
)


def is_admin():
    async def predicate(interaction: discord.Interaction):
        member = interaction.user
        if isinstance(member, discord.Member):
            if member.guild_permissions.administrator:
                return True
            if any(r.id in ADMIN_ROLE_IDS for r in member.roles):
                return True
        await interaction.response.send_message(
            "❌ Admin only.", ephemeral=True
        )
        raise app_commands.CheckFailure("Not admin")

    return app_commands.check(predicate)


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- DB helpers ----------

    async def get_settings(self, guild_id: int):
        assert self.bot.db is not None
        try:
            cur = await self.bot.db.execute(
                """
                SELECT welcome_channel_id, welcome_message, welcome_title, welcome_color, welcome_image_url, autorole_id, default_announce_id, welcome_card_enabled
                FROM guild_settings WHERE guild_id = ?
                """,
                (guild_id,),
            )
        except Exception:
            # Fallback if column missing (though dashboard should handle it)
            return None
            
        row = await cur.fetchone()
        if row is None:
            return None
        return {
            "welcome_channel_id": row[0],
            "welcome_message": row[1],
            "welcome_title": row[2] or "🚨 New Operative Connected",
            "welcome_color": row[3] or "#E74C3C",
            "welcome_image_url": row[4],
            "autorole_id": row[5],
            "default_announce_id": row[6],
            "welcome_card_enabled": row[7] if len(row) > 7 else 0,
        }

    async def upsert_settings(
        self,
        guild_id: int,
        welcome_channel_id: int | None = None,
        welcome_message: str | None = None,
        autorole_id: int | None = None,
        default_announce_id: int | None = None,
    ):
        assert self.bot.db is not None
        current = await self.get_settings(guild_id) or {
            "welcome_channel_id": None,
            "welcome_message": None,
            "welcome_title": "🚨 New Operative Connected",
            "welcome_color": "#E74C3C",
            "welcome_image_url": None,
            "autorole_id": None,
            "default_announce_id": None,
        }

        if welcome_channel_id is not None:
            current["welcome_channel_id"] = welcome_channel_id
        if welcome_message is not None:
            current["welcome_message"] = welcome_message
        if autorole_id is not None:
            current["autorole_id"] = autorole_id
        if default_announce_id is not None:
            current["default_announce_id"] = default_announce_id

        await self.bot.db.execute(
            """
            INSERT INTO guild_settings (guild_id, welcome_channel_id, welcome_message, autorole_id, default_announce_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              welcome_channel_id = excluded.welcome_channel_id,
              welcome_message    = excluded.welcome_message,
              autorole_id        = excluded.autorole_id,
              default_announce_id= excluded.default_announce_id
            """,
            (
                guild_id,
                current["welcome_channel_id"],
                current["welcome_message"],
                current["autorole_id"],
                current["default_announce_id"],
            ),
        )
        await self.bot.db.commit()

    # ---------- event: on_member_join ----------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        settings = await self.get_settings(guild.id) or {}

        rules_channel = guild.get_channel(RULES_CHANNEL_ID) if RULES_CHANNEL_ID else None
        verification_channel = (
            guild.get_channel(VERIFICATION_CHANNEL_ID)
            if VERIFICATION_CHANNEL_ID
            else None
        )

        welcome_channel_id = settings.get("welcome_channel_id") or WELCOME_CHANNEL_ID
        welcome_channel = (
            guild.get_channel(welcome_channel_id) if welcome_channel_id else None
        )

        def replace_vars(text: str) -> str:
            if not text: return ""
            avatar = member.display_avatar.url if member.display_avatar else "https://cdn.discordapp.com/embed/avatars/0.png"
            return text.replace("{mention}", member.mention) \
                       .replace("{server}", guild.name) \
                       .replace("{member_count}", str(guild.member_count)) \
                       .replace("{username}", member.name) \
                       .replace("{display_name}", member.display_name) \
                       .replace("{avatar}", avatar)

        raw_message = settings.get("welcome_message") or (
            "{mention}, welcome to **{server}**.\n"
            "You are now entering a monitored cyber operations zone."
        )
        description = replace_vars(raw_message)

        title = replace_vars(settings.get("welcome_title") or "🚨 New Operative Connected")
        hex_color = settings.get("welcome_color") or "#E74C3C"
        
        try:
            color = discord.Color(int(hex_color.replace("#", ""), 16))
        except ValueError:
            color = discord.Color.red()

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
        )

        file_attachment = None
        img_url = settings.get("welcome_image_url")
        welcome_card = settings.get("welcome_card_enabled")

        if welcome_card:
            import urllib.parse
            
            try:
                safe_user = urllib.parse.quote(member.name)
                safe_server = urllib.parse.quote(guild.name)
                avatar_url = member.display_avatar.url if member.display_avatar else "https://cdn.discordapp.com/embed/avatars/0.png"
                safe_avatar = urllib.parse.quote(str(avatar_url))
                
                theme = settings.get("welcome_card_theme") or "default"
                if theme == "random":
                    import random
                    game_bgs = [
                        "https://images.unsplash.com/photo-1542751371-adc38448a05e?w=1024&h=300&fit=crop", # PUBG/Action
                        "https://images.unsplash.com/photo-1622321406606-25f00115599b?w=1024&h=300&fit=crop", # Minecraft/Blocks
                        "https://images.unsplash.com/photo-1605901309584-818e25960b8f?w=1024&h=300&fit=crop", # GTA/Car
                        "https://images.unsplash.com/photo-1493723843671-1d655e66ac1c?w=1024&h=300&fit=crop", # General Setup
                    ]
                    bg_url = random.choice(game_bgs)
                elif theme == "custom" and img_url:
                    bg_url = replace_vars(img_url)
                else:
                    bg_url = "https://images.unsplash.com/photo-1550684848-fac1c5b4e853?q=80&w=1024&h=300&fit=crop"
                
                safe_bg = urllib.parse.quote(bg_url)
                
                api_url = f"https://api.popcat.xyz/welcomecard?background={safe_bg}&text1={safe_user}&text2=Welcome+to+{safe_server}&text3=Member+{guild.member_count}&avatar={safe_avatar}"
                embed.set_image(url=api_url)
            except Exception as e:
                print(f"Failed generating Popcat welcome card URL: {e}")
                if img_url:
                    embed.set_image(url=replace_vars(img_url))
        elif img_url:
            embed.set_image(url=replace_vars(img_url))

        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        elif guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        if rules_channel:
            embed.add_field(
                name="📜 Briefing",
                value=f"Read {rules_channel.mention} before starting any operation.",
                inline=False,
            )

        if verification_channel:
            embed.add_field(
                name="🧩 Verification",
                value=f"Complete verification in {verification_channel.mention} to unlock the server.",
                inline=False,
            )

        # ----- DM to user (with button that jumps to #verification) -----
        dm_view = None
        if verification_channel:
            dm_view = discord.ui.View()
            url = f"https://discord.com/channels/{guild.id}/{verification_channel.id}"
            dm_view.add_item(
                discord.ui.Button(
                    label="Go to Verification Channel",
                    url=url,
                    style=discord.ButtonStyle.link,
                )
            )

        try:
            await member.send(
                content=f"Welcome to **{guild.name}**, {member.display_name}. 🛰",
                embed=embed,
                view=dm_view,
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        if welcome_channel:
            if file_attachment:
                await welcome_channel.send(content=member.mention, embed=embed, file=file_attachment)
            else:
                await welcome_channel.send(content=member.mention, embed=embed)

        # Autorole
        autorole_id = settings.get("autorole_id")
        if autorole_id:
            role = guild.get_role(autorole_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto role on join")
                except discord.Forbidden:
                    pass

    # ---------- /welcome_set_channel ----------

    @app_commands.command(
        name="welcome_set_channel",
        description="Set the welcome channel.",
    )
    @is_admin()
    async def welcome_set_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await self.upsert_settings(
            interaction.guild.id, welcome_channel_id=channel.id  # type: ignore
        )
        await interaction.response.send_message(
            f"✅ Welcome channel set to {channel.mention}.",
            ephemeral=True,
        )

    # ---------- /welcome_set_message ----------

    @app_commands.command(
        name="welcome_set_message",
        description="Set the welcome message template.",
    )
    @is_admin()
    @app_commands.describe(
        template="Use {mention}, {server}, and {member_count} placeholders.",
    )
    async def welcome_set_message(
        self,
        interaction: discord.Interaction,
        template: str,
    ):
        await self.upsert_settings(
            interaction.guild.id, welcome_message=template  # type: ignore
        )
        await interaction.response.send_message(
            "✅ Welcome message updated.",
            ephemeral=True,
        )

    # ---------- /welcome_set_autorole ----------

    @app_commands.command(
        name="welcome_set_autorole",
        description="Set an autorole for new members.",
    )
    @is_admin()
    async def welcome_set_autorole(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ):
        await self.upsert_settings(
            interaction.guild.id, autorole_id=role.id  # type: ignore
        )
        await interaction.response.send_message(
            f"✅ Autorole set to {role.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
