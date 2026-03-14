# cogs/security_advanced.py
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone, timedelta
from config import ADMIN_ROLE_IDS, LOG_CHANNEL_ID


KNOWN_SCAM_DOMAINS = [
    "discord-nitro.gift", "discordgift.site", "discordapp.gift", "disocrd.com",
    "steancommunity.com", "steamcommunnity.com", "free-nitro.gg", "nitro-discord.gift",
    "discord.gift.com", "freeskins.gg", "csgo-earnings.com"
]


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


class SecurityAdvancedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_scam_domains(self, guild_id: int) -> list[str]:
        cur = await self.bot.db.execute(
            "SELECT domain FROM scam_domains WHERE guild_id=?", (guild_id,)
        )
        rows = await cur.fetchall()
        return [r[0].lower() for r in rows]

    # ---------- Ghost Ping Detector ----------

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Check if the message had mentions
        if message.mentions or message.role_mentions:
            log_ch = message.guild.get_channel(LOG_CHANNEL_ID)
            if isinstance(log_ch, discord.TextChannel):
                embed = discord.Embed(
                    title="👻 Ghost Ping Detected!",
                    description=(
                        f"**User:** {message.author.mention}\n"
                        f"**Channel:** {message.channel.mention}\n"
                        f"**Message Preview:** `{message.content[:200]}`"
                    ),
                    color=discord.Color.dark_purple()
                )
                mentions_str = " ".join([m.mention for m in message.mentions] + [r.mention for r in message.role_mentions][:10])
                embed.add_field(name="Pinged:", value=mentions_str or "Unknown", inline=False)
                await log_ch.send(embed=embed)

    # ---------- Anti-Spam (Velocity) ----------

    @commands.Cog.listener("on_message")
    async def anti_spam_listener(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if isinstance(message.author, discord.Member) and message.author.guild_permissions.administrator:
            return

        cur = await self.bot.db.execute("SELECT messages, seconds FROM anti_nuke_config WHERE guild_id=?", (message.guild.id,))
        row = await cur.fetchone()
        if not row:
            return  # Not configured

        limit_msgs, limit_secs = row
        now = datetime.now(timezone.utc)
        
        # We need a robust sliding window cache, but a simple in-memory one works for velocity tracking
        if not hasattr(self, "_spam_cache"):
            self._spam_cache = {}  # guild_id -> {user_id: [timestamps]}

        if message.guild.id not in self._spam_cache:
            self._spam_cache[message.guild.id] = {}
        if message.author.id not in self._spam_cache[message.guild.id]:
            self._spam_cache[message.guild.id][message.author.id] = []

        # Add current timestamp
        user_cache = self._spam_cache[message.guild.id][message.author.id]
        user_cache.append(now)

        # Remove old timestamps
        user_cache[:] = [t for t in user_cache if (now - t).total_seconds() <= limit_secs]

        if len(user_cache) >= limit_msgs:
            # Trigger mute
            user_cache.clear()
            member = message.author
            duration = timedelta(hours=1)
            try:
                await member.timeout(duration, reason="[AutoMod] Spam velocity exceeded")
                
                log_ch = message.guild.get_channel(LOG_CHANNEL_ID)
                if isinstance(log_ch, discord.TextChannel):
                    emb = discord.Embed(
                        title="🛑 Anti-Spam Triggered",
                        description=f"**{member.mention}** was muted for **1 hour**.\nReason: Sent **{limit_msgs}** messages in **{limit_secs}** seconds.",
                        color=discord.Color.red()
                    )
                    await log_ch.send(embed=emb)
                
                await message.channel.send(f"⚠️ {member.mention} has been silenced for spamming.", delete_after=10)
            except discord.Forbidden:
                pass

    # ---------- /anti_nuke_setup ----------

    @app_commands.command(name="anti_nuke_setup", description="Configure the Anti-Spam velocity tracking.")
    @is_admin()
    @app_commands.describe(messages="Max messages allowed.", seconds="Time window in seconds.")
    async def anti_nuke_setup(self, interaction: discord.Interaction, messages: int, seconds: int):
        if messages < 3 or seconds < 1:
            await interaction.response.send_message("❌ Minimum 3 messages and 1 second.", ephemeral=True)
            return

        await self.bot.db.execute(
            """INSERT INTO anti_nuke_config (guild_id, messages, seconds) VALUES (?,?,?)
               ON CONFLICT(guild_id) DO UPDATE SET messages=?, seconds=?""",
            (interaction.guild.id, messages, seconds, messages, seconds)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Anti-Spam active! Muting users who send **{messages}** messages within **{seconds}** seconds.", ephemeral=True)

    # ---------- Alt Account Detector ----------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        account_age = datetime.now(timezone.utc) - member.created_at
        if account_age < timedelta(days=7):
            log_ch = guild.get_channel(LOG_CHANNEL_ID)
            if isinstance(log_ch, discord.TextChannel):
                embed = discord.Embed(
                    title="🚨 New Account Alert",
                    description=(
                        f"**{member.mention}** joined with a **very new account!**\n"
                        f"Account created: <t:{int(member.created_at.timestamp())}:R>\n"
                        f"Age: **{account_age.days}d {account_age.seconds // 3600}h**\n\n"
                        f"⚠️ This could be an **alt account** or bot. Monitor accordingly."
                    ),
                    color=discord.Color.orange()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=f"User ID: {member.id}")
                await log_ch.send(embed=embed)

    # ---------- Scam Link Filter ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if isinstance(message.author, discord.Member) and message.author.guild_permissions.administrator:
            return

        content_lower = message.content.lower()
        # Check built-in list + guild-specific list
        all_domains = KNOWN_SCAM_DOMAINS + await self.get_scam_domains(message.guild.id)

        detected = next((d for d in all_domains if d in content_lower), None)
        if not detected:
            return

        try:
            await message.delete()
        except discord.Forbidden:
            pass

        log_ch = message.guild.get_channel(LOG_CHANNEL_ID)
        embed = discord.Embed(
            title="🛑 Scam Link Blocked",
            description=(
                f"**User:** {message.author.mention}\n"
                f"**Channel:** {message.channel.mention}\n"
                f"**Detected domain:** `{detected}`\n"
                f"**Message preview:** `{message.content[:100]}`"
            ),
            color=discord.Color.red()
        )
        if isinstance(log_ch, discord.TextChannel):
            await log_ch.send(embed=embed)

        try:
            await message.channel.send(
                f"🛑 {message.author.mention}, your message was removed — it contained a known scam/phishing link.",
                delete_after=8
            )
        except Exception:
            pass

    # ---------- /scam_add ----------

    @app_commands.command(name="scam_add", description="Add a domain to the scam blocklist. (Admin)")
    @is_admin()
    @app_commands.describe(domain="Domain to block (e.g. free-nitro.gg).")
    async def scam_add(self, interaction: discord.Interaction, domain: str):
        domain = domain.lower().strip()
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO scam_domains (guild_id, domain) VALUES (?,?)",
            (interaction.guild.id, domain)
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ `{domain}` added to scam blocklist.", ephemeral=True)

    # ---------- /scam_remove ----------

    @app_commands.command(name="scam_remove", description="Remove a domain from the scam blocklist. (Admin)")
    @is_admin()
    @app_commands.describe(domain="Domain to unblock.")
    async def scam_remove(self, interaction: discord.Interaction, domain: str):
        await self.bot.db.execute(
            "DELETE FROM scam_domains WHERE guild_id=? AND domain=?",
            (interaction.guild.id, domain.lower())
        )
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ `{domain}` removed from blocklist.", ephemeral=True)

    # ---------- /scam_list ----------

    @app_commands.command(name="scam_list", description="View the current scam domain blocklist.")
    async def scam_list(self, interaction: discord.Interaction):
        custom = await self.get_scam_domains(interaction.guild.id)
        embed = discord.Embed(title="🛑 Scam Domain Blocklist", color=discord.Color.red())
        embed.add_field(
            name="Built-in Domains",
            value="\n".join(f"`{d}`" for d in KNOWN_SCAM_DOMAINS) or "None",
            inline=False
        )
        embed.add_field(
            name="Custom (Server)",
            value="\n".join(f"`{d}`" for d in custom) or "None added yet.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SecurityAdvancedCog(bot))
