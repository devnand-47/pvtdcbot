# cogs/help.py

import discord
from discord.ext import commands
from discord import app_commands


class HelpDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Home & Overview", description="Return to the main help menu.", emoji="🏠", value="home"),
            discord.SelectOption(label="Admin & Setup", description="Bots settings, setup J2C and counting.", emoji="🛡️", value="admin"),
            discord.SelectOption(label="Moderation & Warns", description="Mute, ban, warnings, and clear messages.", emoji="🔨", value="moderation"),
            discord.SelectOption(label="Advanced Security", description="Scam filters, alts, and anti-nuke.", emoji="🚨", value="security"),
            discord.SelectOption(label="Welcome & Config", description="Welcome, AutoRole, and server stats.", emoji="📥", value="config"),
            discord.SelectOption(label="Support Tickets", description="Interactive support ticket panels.", emoji="🎫", value="tickets"),
            discord.SelectOption(label="Economy & Casino", description="Shop, coins, slots, and blackjack.", emoji="💰", value="economy"),
            discord.SelectOption(label="RPG & Pets", description="Adopt pets, quest, and level them up.", emoji="🐉", value="rpg"),
            discord.SelectOption(label="Leveling & Streaks", description="Rank cards, message streaks, leaderboards.", emoji="⭐", value="leveling"),
            discord.SelectOption(label="Roleplay & Social", description="Marriage, hugs, slaps, and anime gifs.", emoji="💖", value="roleplay"),
            discord.SelectOption(label="Image Memes", description="Wanted posters, jail bars, and wasted.", emoji="🖼️", value="images"),
            discord.SelectOption(label="Fun & Games", description="Trivia, rock-paper-scissors, guess, coinflip.", emoji="🎮", value="games"),
            discord.SelectOption(label="AI & Bot Info", description="Agent 47 AI chat, ping, memes.", emoji="🤖", value="ai"),
            discord.SelectOption(label="Music & Soundboard", description="Music player, queues, and sound clips.", emoji="🎵", value="music"),
            discord.SelectOption(label="Events & Giveaways", description="Birthday wishes and timed giveaways.", emoji="🎉", value="events"),
            discord.SelectOption(label="Utilities", description="Quotes, reminders, and J2C Voice.", emoji="🛠️", value="utils"),
            discord.SelectOption(label="Web Dashboard", description="Manage web settings.", emoji="🌐", value="dashboard"),
        ]
        super().__init__(placeholder="Select a command category...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        v = self.values[0]

        if v == "home":
            embed = build_home_embed(interaction.client)

        elif v == "admin":
            embed = discord.Embed(title="🛡️ Admin & Setup", color=discord.Color.red())
            embed.add_field(name="`/announce <msg> [channel]`", value="Broadcast a professional server announcement.", inline=False)
            embed.add_field(name="`/say <msg> [ch]`", value="Send a raw message to any channel.", inline=False)
            embed.add_field(name="`/poll <q> <opts...>`", value="Create a reaction-vote poll.", inline=False)
            embed.add_field(name="`/lockdown` / `/slowmode <s>`", value="Lock a channel or restrict chat speed.", inline=False)
            embed.add_field(name="`/backup_now`", value="Generate a JSON backup of server messages.", inline=False)
            embed.add_field(name="`/maintenance`", value="Put the bot into maintenance mode.", inline=False)

        elif v == "moderation":
            embed = discord.Embed(title="🔨 Moderation & Warnings", color=discord.Color.orange())
            embed.add_field(name="`/warn @user <reason>`", value="Issue a DB-logged warning. Auto-actions at thresholds.", inline=False)
            embed.add_field(name="`/warnings @user`", value="View warning history.", inline=False)
            embed.add_field(name="`/clearwarn` / `/clearwarns`", value="Clear one or all warnings.", inline=False)
            embed.add_field(name="`/warn_config`", value="Set thresholds for auto-mute/kick/ban.", inline=False)
            embed.add_field(name="`/tempmute @user <time> [reason]`", value="Timeout: `10s`, `5m`, `1d`.", inline=False)
            embed.add_field(name="`/tempban @user <time> [reason]`", value="Ban and auto-unban after time expires.", inline=False)
            embed.add_field(name="`/unmute @user`", value="Remove an active timeout.", inline=False)
            embed.add_field(name="`/kick` / `/ban` / `/clear <qty>`", value="Standard moderation actions.", inline=False)

        elif v == "security":
            embed = discord.Embed(title="🚨 Advanced Security", color=discord.Color.dark_red())
            embed.add_field(name="Alt Detector", value="Auto-flags accounts < 7 days old on join.", inline=False)
            embed.add_field(name="Scam Link Filter", value="Auto-deletes known malicious domains instantly.", inline=False)
            embed.add_field(name="Anti-Spam (Velocity)", value="Auto-mutes members who send too many messages too quickly.", inline=False)
            embed.add_field(name="Ghost Ping Detector", value="Catches members who mention someone and immediately delete their message.", inline=False)
            embed.add_field(name="`/anti_nuke_setup`", value="**Admin:** Configure the Anti-Spam velocity tracking settings.", inline=False)
            embed.add_field(name="`/scam_add <domain>`", value="Add a custom domain to block.", inline=False)
            embed.add_field(name="`/scam_remove <domain>`", value="Remove a domain from blocklist.", inline=False)
            embed.add_field(name="`/scam_list`", value="View currently blocked scam domains.", inline=False)
            embed.add_field(name="`/invites [@user]`", value="Check how many real users someone invited.", inline=False)
            embed.add_field(name="`/invite_leaderboard`", value="Top 10 recruiters.", inline=False)

        elif v == "config":
            embed = discord.Embed(title="📥 Welcome & Config", color=discord.Color.green())
            embed.add_field(name="Welcome System", value="Configure Welcome Channel and beautiful background images entirely on the Web Dashboard.", inline=False)
            embed.add_field(name="AutoRole", value="Auto-assign a role to new members (set on dashboard).", inline=False)
            embed.add_field(name="`/stats_setup`", value="Create auto-updating Server Stats voice channels.", inline=False)

        elif v == "tickets":
            embed = discord.Embed(title="🎫 Support Tickets", color=discord.Color.blue())
            embed.add_field(name="`/ticket_panel`", value="**Admin:** Deploy an interactive 'Open Ticket' button.", inline=False)
            embed.add_field(name="Using Tickets", value="Generates private channels and logs transcripts to the dashboard.", inline=False)

        elif v == "economy":
            embed = discord.Embed(title="💰 Economy & Shop", color=discord.Color.gold())
            embed.add_field(name="`/daily`", value="Claim daily coin reward.", inline=False)
            embed.add_field(name="`/balance [@member]`", value="Check coin balance (also earn coins automatically by chatting).", inline=False)
            embed.add_field(name="`/give @user <amount>`", value="Transfer coins to someone else.", inline=False)
            embed.add_field(name="`/leaderboard_coins`", value="View the richest members.", inline=False)
            embed.add_field(name="`/shop`", value="Browse roles available for purchase.", inline=False)
            embed.add_field(name="`/buy <item>`", value="Purchase an item with your coins.", inline=False)
            embed.add_field(name="`/shop_add <name> <price> [@role]`", value="**Admin:** Add items to shop.", inline=False)
            embed.add_field(name="**— Casino —**", value="\u200b", inline=False)
            embed.add_field(name="`/slots <bet>`", value="Spin the slot machine.", inline=False)
            embed.add_field(name="`/blackjack <bet>`", value="Play a hand of blackjack against the dealer.", inline=False)
            embed.add_field(name="`/roulette <bet> <choice>`", value="Bet on red, black, or green.", inline=False)

        elif v == "rpg":
            embed = discord.Embed(title="🐉 RPG & Pets", color=discord.Color.dark_green())
            embed.add_field(name="`/pet_buy <name>`", value="Adopt a pet to hunt for coins.", inline=False)
            embed.add_field(name="`/pet_info`", value="View your pet's stats, level, and XP.", inline=False)
            embed.add_field(name="`/quest`", value="Send your pet on a quest. Higher levels yield more bonus coins (5m cooldown).", inline=False)

        elif v == "leveling":
            embed = discord.Embed(title="⭐ Leveling & Streaks", color=discord.Color.teal())
            embed.add_field(name="`/rank [@user]`", value="View current Rank, Level, and XP.", inline=False)
            embed.add_field(name="`/leaderboard`", value="Top chatters.", inline=False)
            embed.add_field(name="`/voiceleaderboard`", value="Top talkers.", inline=False)
            embed.add_field(name="`/streak`", value="Check your daily message streak (earns bonus coins!).", inline=False)
            embed.add_field(name="`/streak_leaderboard`", value="Top active streaks.", inline=False)

        elif v == "roleplay":
            embed = discord.Embed(title="💖 Roleplay & Social", color=discord.Color.from_rgb(255, 105, 180))
            embed.add_field(name="`/marry @user`", value="Propose marriage (costs 10,000 coins for a ring).", inline=False)
            embed.add_field(name="`/divorce`", value="Break off your marriage.", inline=False)
            embed.add_field(name="`/hug @user`", value="Give someone a warm hug.", inline=False)
            embed.add_field(name="`/pat @user`", value="Pat someone on the head.", inline=False)
            embed.add_field(name="`/slap @user`", value="Slap some sense into someone.", inline=False)

        elif v == "images":
            embed = discord.Embed(title="🖼️ Image Memes", color=discord.Color.dark_purple())
            embed.add_field(name="`/wanted [@user]`", value="Put a user on a wanted poster.", inline=False)
            embed.add_field(name="`/jail [@user]`", value="Put a user behind bars.", inline=False)
            embed.add_field(name="`/wasted [@user]`", value="Apply the GTA Wasted effect.", inline=False)
            embed.add_field(name="`/clown [@user]`", value="Expose them as an absolute clown.", inline=False)

        elif v == "games":
            embed = discord.Embed(title="🎮 Fun & Games", color=discord.Color.purple())
            embed.add_field(name="`/rps <choice>`", value="Play Rock, Paper, Scissors vs the bot.", inline=False)
            embed.add_field(name="`/trivia`", value="Answer multiple-choice trivia questions.", inline=False)
            embed.add_field(name="`/guess`", value="Guess the number between 1 and 100 (5 attempts).", inline=False)
            embed.add_field(name="`/coinflip [bet] [side]`", value="Flip a coin, optionally bet your economy coins on it.", inline=False)

        elif v == "ai":
            embed = discord.Embed(title="🤖 AI & Bot Info", color=discord.Color.greyple())
            embed.add_field(name="`/ai <message>`", value="Chat with Agent 47.", inline=False)
            embed.add_field(name="`!ping`", value="Advanced cluster diagnostics.", inline=False)
            embed.add_field(name="`!meme` / `!8ball`", value="Reddit memes and answers.", inline=False)

        elif v == "music":
            embed = discord.Embed(title="🎵 Music & Soundboard", color=discord.Color.blurple())
            embed.add_field(name="**— Music —**", value="`/connect`, `/play <url/search>`, `/skip`, `/stop`, `/pause`, `/queue`, `/volume`, `/disconnect`", inline=False)
            embed.add_field(name="**— Soundboard —**", value="`/soundboard <name>`, `/soundboard_list`, `/soundboard_stop`\nAdmin: `/soundboard_add <name> [file]`, `/soundboard_remove`", inline=False)

        elif v == "events":
            embed = discord.Embed(title="🎉 Events & Giveaways", color=discord.Color.from_rgb(255, 105, 180))
            embed.add_field(name="**— Giveaways —**", value="`/giveaway <time> <prize> [winners]` — Start a timed giveaway.\n`/giveaway_reroll <msg_id>` — Pick a new winner.", inline=False)
            embed.add_field(name="**— Birthdays —**", value="`/birthday <month> <day>` — Set your birthday.\n`/birthday_channel #ch` (Admin) — Where wishes go.", inline=False)

        elif v == "utils":
            embed = discord.Embed(title="🛠️ Utilities", color=discord.Color.dark_theme())
            embed.add_field(name="`/remind <time> <message>`", value="Set a persistent DM reminder (`10m`, `2h`, `1d`).", inline=False)
            embed.add_field(name="`/reminders`", value="View your active reminders.", inline=False)
            embed.add_field(name="`/quote_add @user \"text\"`", value="Archive a funny/memorable quote permanently.", inline=False)
            embed.add_field(name="`/quote` / `/quote_list`", value="Fetch a random quote or the last 10.", inline=False)
            embed.add_field(name="`/counting_setup #channel`", value="**Admin:** Start a sequence counting channel. Resets on typos!", inline=False)
            embed.add_field(name="**— Join-to-Create (J2C) —**", value="\u200b", inline=False)
            embed.add_field(name="`/j2c_setup`", value="**Admin:** Setup automated private temporary voice channels.", inline=False)
            embed.add_field(name="`/vc_lock` / `/vc_unlock`", value="Lock or unlock your temporary private voice channel.", inline=False)

        elif v == "dashboard":
            embed = discord.Embed(title="🌐 Web Dashboard", color=discord.Color.teal())
            embed.add_field(name="Access Dashboard", value="Open `http://localhost:8000/` in your browser.", inline=False)
            embed.add_field(name="Dashboard Features", value="Configure AI settings, setup Reaction Roles, create Custom Text Commands, track YouTube uploads (`/youtube`), and view live server stats.", inline=False)

        else:
            embed = build_home_embed(interaction.client)

        await interaction.response.edit_message(embed=embed)


def build_home_embed(bot: commands.Bot) -> discord.Embed:
    embed = discord.Embed(
        title="Agent 47 — Complete Function Guide",
        description=(
            "The Mega Bundle is live. Your cyber-security assistant now possesses **11 new advanced features**.\n\n"
            "Use the **dropdown menu** below to navigate through the 14 operational categories.\n"
        ),
        color=discord.Color.teal(),
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(
        name="🛠️ Core Systems",
        value=(
            "🛡️ Admin & Setup\n"
            "🔨 Moderation & Warns\n"
            "🚨 Advanced Security\n"
            "📥 Welcome & Config\n"
            "🎫 Support Tickets"
        ),
        inline=True,
    )
    embed.add_field(
        name="🎮 Engagement",
        value=(
            "💰 Economy & Casino\n"
            "🐉 RPG & Pets\n"
            "💖 Roleplay & Marriage\n"
            "⭐ Leveling & Streaks\n"
            "🎮 Fun & Minigames\n"
            "🎵 Music & Sounds\n"
            "🎉 Events & Giveaways"
        ),
        inline=True,
    )
    embed.add_field(
        name="⚙️ Miscellaneous",
        value=(
            "🤖 AI Chat\n"
            "🖼️ Image Memes\n"
            "🛠️ Quotes, J2C & Utils\n"
            "🌐 Web Dashboard"
        ),
        inline=True,
    )
    embed.set_footer(text="Agent 47 | Developed by Agent47@640509__0401_47")
    return embed


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(HelpDropdown())


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Complete interactive guide for all Agent 47 commands.")
    async def help_slash(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_home_embed(self.bot), view=HelpView(), ephemeral=True)

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context):
        await ctx.send(embed=build_home_embed(self.bot), view=HelpView())


async def setup(bot: commands.Bot):
    bot.remove_command("help")
    await bot.add_cog(HelpCog(bot))
