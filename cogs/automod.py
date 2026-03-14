# cogs/automod.py

import time
import re
import random
from collections import defaultdict
from typing import Dict, Tuple, Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands

from config import (
    ADMIN_ROLE_IDS,
    LOG_CHANNEL_ID,
    VERIFICATION_CHANNEL_ID,
    VERIFIED_ROLE_ID,
    RAID_JOIN_WINDOW,
    RAID_JOIN_THRESHOLD,
    LOCKDOWN_HARD_THRESHOLD,
    FIREWALL_AUTO_RELEASE_MINUTES,
    CAPTCHA_EXPIRE_SECONDS,
)

# ---------- BASIC FILTERS ----------

BAD_WORDS = {"badword1", "badword2"}  # fill with real words
INVITE_RE = re.compile(r"(discord\.gg/|discord\.com/invite/)", re.IGNORECASE)

SPAM_WINDOW = 5        # seconds
SPAM_MAX_MSG = 5       # messages in window


def is_admin_member(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.id in ADMIN_ROLE_IDS for r in member.roles)


def admin_check():
    async def predicate(interaction: discord.Interaction):
        member = interaction.user
        if isinstance(member, discord.Member) and is_admin_member(member):
            return True
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        raise app_commands.CheckFailure("Not admin")
    return app_commands.check(predicate)


# ---------- CAPTCHA VIEW ----------

class CaptchaView(discord.ui.View):
    def __init__(self, cog: "AutoModCog", member: discord.Member, code: int):
        super().__init__(timeout=CAPTCHA_EXPIRE_SECONDS)
        self.cog = cog
        self.member = member
        self.correct_code = str(code)

        # create 3 buttons, one is correct
        options = {self.correct_code}
        while len(options) < 3:
            options.add(str(random.randint(1000, 9999)))
        labels = list(options)
        random.shuffle(labels)

        for label in labels:
            self.add_item(CaptchaButton(label, self))

    async def on_timeout(self):
        # if still pending, mark as expired (no extra action needed here;
        # cog can clean when needed)
        pass


class CaptchaButton(discord.ui.Button):
    def __init__(self, label: str, view: CaptchaView):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.cog_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.cog_view.member.id:
            await interaction.response.send_message(
                "This verification is not for you.", ephemeral=True
            )
            return

        if self.label == self.cog_view.correct_code:
            await self.cog_view.cog.captcha_success(self.cog_view.member, interaction)
        else:
            await interaction.response.send_message(
                "❌ Wrong code. Try again.", ephemeral=True
            )


# ---------- MAIN COG ----------

class AutoModCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # spam tracking: user_id -> timestamps
        self.msg_history: Dict[int, list[float]] = defaultdict(list)
        # join tracking: timestamps
        self.join_times: list[float] = []
        # firewall state
        self.firewall_enabled: bool = False
        self.last_raid_time: float = 0.0
        # captcha pending: user_id -> (code, timestamp)
        self.pending_captcha: Dict[int, Tuple[str, float]] = {}

        self.firewall_watchdog.start()

    def cog_unload(self):
        self.firewall_watchdog.cancel()

    # ---------- LOG HELPERS ----------

    async def log_channel(self, guild: discord.Guild, text: str):
        chan = guild.get_channel(LOG_CHANNEL_ID)
        if isinstance(chan, discord.TextChannel):
            await chan.send(text)

    async def log_db(
        self,
        guild_id: int,
        user_id: Optional[int],
        actor_id: Optional[int],
        action: str,
        reason: str = "",
    ):
        db = getattr(self.bot, "db", None)
        if not db:
            return
        ts = int(time.time())
        await db.execute(
            """
            INSERT INTO moderation_logs (guild_id, user_id, actor_id, action, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, actor_id, action, reason, ts),
        )
        await db.commit()

    async def get_settings(self, guild_id: int):
        db = getattr(self.bot, "db", None)
        if not db:
            return {"automod": 0, "firewall": 0, "spam": 0, "bad_words": ""}
        cur = await db.execute(
            """
            SELECT automod_enabled, firewall_enabled, spam_protection_enabled, bad_words
            FROM guild_settings WHERE guild_id = ?
            """,
            (guild_id,),
        )
        row = await cur.fetchone()
        if not row:
            return {"automod": 0, "firewall": 0, "spam": 0, "bad_words": ""}
            
        return {
            "automod": row[0] or 0,
            "firewall": row[1] or 0,
            "spam": row[2] or 0,
            "bad_words": row[3] or ""
        }

    # ---------- FIREWALL / LOCKDOWN ----------

    async def enable_firewall(self, guild: discord.Guild, reason: str, actor_id: Optional[int] = None):
        if self.firewall_enabled:
            return
        self.firewall_enabled = True
        self.last_raid_time = time.time()
        await self.log_channel(
            guild,
            f"🚨 Firewall mode **ENABLED** – new members will be CAPTCHA-verified.\nReason: {reason}",
        )
        await self.log_db(guild.id, None, actor_id, "firewall_on", reason)

    async def disable_firewall(self, guild: discord.Guild, actor_id: Optional[int] = None):
        if not self.firewall_enabled:
            return
        self.firewall_enabled = False
        await self.log_channel(
            guild,
            "✅ Firewall mode **DISABLED** – new members join normally again.",
        )
        await self.log_db(guild.id, None, actor_id, "firewall_off", "")

    async def temporary_lockdown(self, guild: discord.Guild, actor_id: Optional[int], reason: str):
        await self.log_channel(
            guild,
            "🛑 **TEMPORARY LOCKDOWN** – most channels locked due to raid.",
        )
        for ch in guild.text_channels:
            try:
                overwrites = ch.overwrites_for(guild.default_role)
                if overwrites.send_messages is not False:
                    overwrites.send_messages = False
                    await ch.set_permissions(
                        guild.default_role,
                        overwrite=overwrites,
                        reason="Raid lockdown",
                    )
            except discord.Forbidden:
                continue
        await self.log_db(guild.id, None, actor_id, "lockdown_on", reason)

    # auto-release firewall when calm (disabled if FIREWALL_AUTO_RELEASE_MINUTES <= 0)
    @tasks.loop(minutes=1)
    async def firewall_watchdog(self):
        if not self.firewall_enabled or FIREWALL_AUTO_RELEASE_MINUTES <= 0:
            return
        now = time.time()
        if now - self.last_raid_time > FIREWALL_AUTO_RELEASE_MINUTES * 60:
            for g in self.bot.guilds:
                await self.disable_firewall(g)

    @firewall_watchdog.before_loop
    async def before_firewall_watchdog(self):
        await self.bot.wait_until_ready()

    # ---------- CAPTCHA FLOW ----------

    async def start_captcha(self, member: discord.Member):
        guild = member.guild
        code = str(random.randint(1000, 9999))
        self.pending_captcha[member.id] = (code, time.time())

        view = CaptchaView(self, member, int(code))

        msg_text = (
            f"{member.mention}, firewall mode is active.\n"
            f"Complete this challenge to access the server.\n"
            f"Select the button that shows your code: **{code}**"
        )

        # Prefer verification channel
        verification_channel = guild.get_channel(VERIFICATION_CHANNEL_ID)
        if isinstance(verification_channel, discord.TextChannel):
            await verification_channel.send(msg_text, view=view)
        else:
            try:
                await member.send(msg_text, view=view)
            except discord.Forbidden:
                await self.log_channel(
                    guild,
                    f"⚠️ Could not DM verification to {member} (DMs closed). Ask them to enable DMs.",
                )

        await self.log_db(guild.id, member.id, None, "captcha_start", f"User: {member.name}")

    async def captcha_success(self, member: discord.Member, interaction: discord.Interaction):
        guild = member.guild
        # remove from pending
        self.pending_captcha.pop(member.id, None)

        # delete the verification message with buttons
        try:
            if interaction.message:
                await interaction.message.delete()
        except discord.Forbidden:
            pass

        # remove channel overrides that blocked sending (if any)
        for ch in guild.text_channels:
            try:
                await ch.set_permissions(member, overwrite=None, reason="Captcha passed")
            except discord.Forbidden:
                continue

        # assign verified role
        if VERIFIED_ROLE_ID:
            role = guild.get_role(VERIFIED_ROLE_ID)
            if role:
                try:
                    await member.add_roles(role, reason="Captcha passed")
                except discord.Forbidden:
                    pass

        await interaction.response.send_message(
            "✅ Verification complete. Welcome to the server.", ephemeral=True
        )
        await self.log_channel(guild, f"✅ {member.mention} passed CAPTCHA verification.")
        await self.log_db(guild.id, member.id, interaction.user.id, "captcha_pass", f"User: {member.name}")

    # ---------- LISTENERS ----------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot or not member.guild:
            return

        guild = member.guild
        now = time.time()
        
        settings = await self.get_settings(guild.id)
        if hasattr(self, "firewall_enabled"):
            self.firewall_enabled = bool(settings["firewall"])

        # track joins for raid detection
        self.join_times.append(now)
        self.join_times = [t for t in self.join_times if now - t <= RAID_JOIN_WINDOW]

        await self.log_db(guild.id, member.id, None, "join", "")

        # RAID detection
        join_count = len(self.join_times)
        if join_count >= RAID_JOIN_THRESHOLD:
            await self.enable_firewall(
                guild,
                f"{join_count} joins in {RAID_JOIN_WINDOW}s (auto)",
                None,
            )

        if join_count >= LOCKDOWN_HARD_THRESHOLD:
            await self.temporary_lockdown(
                guild,
                None,
                f"{join_count} joins in {RAID_JOIN_WINDOW}s (auto lockdown)",
            )

        # If firewall active, apply CAPTCHA for this member
        if self.firewall_enabled:
            # block sending everywhere via overrides
            for ch in guild.text_channels:
                try:
                    await ch.set_permissions(
                        member,
                        send_messages=False,
                        add_reactions=False,
                        reason="Firewall verification",
                    )
                except discord.Forbidden:
                    continue
            await self.start_captcha(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot or not member.guild:
            return
        await self.log_db(member.guild.id, member.id, None, "leave", "")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        member = message.author
        guild = message.guild

        if isinstance(member, discord.Member) and is_admin_member(member):
            return  # ignore staff

        content_lower = message.content.lower()
        settings = await self.get_settings(guild.id)
        
        # Parse bad words dynamically
        bw_string = settings.get("bad_words", "")
        dynamic_bad_words = [w.strip().lower() for w in bw_string.split(",") if w.strip()] if bw_string else []

        # Bad words
        if bool(settings.get("automod")):
            if any(bad in content_lower for bad in dynamic_bad_words):
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                await self.log_channel(
                    guild,
                    f"🧱 Deleted bad-word message from {member.mention} in {message.channel.mention}.",
                )
                await self.log_db(guild.id, member.id, None, "badword_delete", "")
                return

            # Anti-link (Discord invites)
            if INVITE_RE.search(message.content):
                try:
                    await message.delete()
                except discord.Forbidden:
                    pass
                await self.log_channel(
                    guild,
                    f"⛔ Deleted invite link from {member.mention} in {message.channel.mention}.",
                )
                await self.log_db(guild.id, member.id, None, "invite_delete", "")
                return

        # Anti-spam
        if bool(settings.get("spam")):
            now = time.time()
            hist = self.msg_history[member.id]
            hist.append(now)
            self.msg_history[member.id] = [t for t in hist if now - t <= SPAM_WINDOW]
            if len(self.msg_history[member.id]) > SPAM_MAX_MSG:
                try:
                    await message.channel.set_permissions(
                        member,
                        send_messages=False,
                        reason="AutoMod spam mute",
                    )
                except discord.Forbidden:
                    pass
                await self.log_channel(
                    guild,
                    f"🔇 Auto-muted {member.mention} for spam in {message.channel.mention}.",
                )
                await self.log_db(guild.id, member.id, None, "spam_mute", "")

    # ---------- ADMIN SLASH COMMANDS ----------

    @app_commands.command(
        name="firewall",
        description="Manage raid firewall mode (auto-raid protection).",
    )
    @admin_check()
    @app_commands.describe(mode="on/off/status")
    async def firewall(
        self,
        interaction: discord.Interaction,
        mode: str,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild not found.", ephemeral=True)
            return

        mode = mode.lower()
        if mode == "on":
            await self.enable_firewall(guild, "Manual enable", interaction.user.id)
            await interaction.response.send_message("✅ Firewall enabled.", ephemeral=True)
        elif mode == "off":
            await self.disable_firewall(guild, interaction.user.id)
            await interaction.response.send_message("✅ Firewall disabled.", ephemeral=True)
        elif mode == "status":
            status = "ENABLED" if self.firewall_enabled else "DISABLED"
            await interaction.response.send_message(
                f"Firewall status: **{status}**\n"
                f"Recent joins in {RAID_JOIN_WINDOW}s: {len(self.join_times)}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Usage: `/firewall mode:on|off|status`", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoModCog(bot))
