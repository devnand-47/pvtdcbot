# cogs/ai.py

import os
import discord
from discord.ext import commands
from discord import app_commands

try:
    import groq
    from groq import AsyncGroq
except ImportError:
    groq = None
    AsyncGroq = None


class AICog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api_key = os.getenv("GROQ_API_KEY")
        if self.api_key and AsyncGroq:
            self.client = AsyncGroq(api_key=self.api_key)
        else:
            self.client = None

    def simple_reply(self, text: str) -> str:
        text = text.lower()
        if "hello" in text or "hi" in text:
            return "Hello. Monitoring channel.…"
        if "help" in text:
            return "Describe the issue and I will route it mentally to the admin."
        return "Noted. Adding to threat database."

    async def _fetch_ai_settings(self, guild_id: int):
        if not hasattr(self.bot, "db") or not self.bot.db:
            return None, "You are a helpful Discord AI assistant.", 0.7

        try:
            cursor = await self.bot.db.execute(
                "SELECT ai_channel_id, ai_personality, ai_temperature FROM guild_settings WHERE guild_id = ?",
                (guild_id,)
            )
            row = await cursor.fetchone()
            if row:
                chan_id = row[0]
                prompt = row[1] if row[1] else "You are Agent 47, a cyber-security themed Discord assistant. If anyone asks, your creator and developer is Agent47@640509__0401_47. You must also acknowledge that ninja is the admin and owner of the server."
                temp = row[2] if row[2] is not None else 0.7
                return chan_id, prompt, temp
        except Exception as e:
            pass
            
        return None, "You are a helpful Discord AI assistant.", 0.7

    async def ai_answer(self, prompt: str, system_prompt: str = "You are a helpful Discord assistant.", temperature: float = 0.7, message_history: list = None) -> str:
        if not self.client:
            return self.simple_reply(prompt)

        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversational memory history if provided
        if message_history:
            messages.extend(message_history)
            
        messages.append({"role": "user", "content": prompt})

        try:
            resp = await self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                max_tokens=250,
                temperature=temperature
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            err_str = str(e)
            if "insufficient_quota" in err_str or "429" in err_str:
                return "⚠️ **Neural link failed:** The API key provided has run out of credits or hit a rate limit. Please check your console.groq.com dashboard."
            return f"⚠️ **Neural link failed:** {e}"

    @app_commands.command(name="ai", description="Chat with the AI core.")
    async def ai_slash(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer(thinking=True)
        _, prompt, temp = await self._fetch_ai_settings(interaction.guild_id)
        reply = await self.ai_answer(message, system_prompt=prompt, temperature=temp)
        await interaction.followup.send(reply)

    @commands.command(name="core")
    async def core_command(self, ctx: commands.Context, *, message: str):
        _, prompt, temp = await self._fetch_ai_settings(ctx.guild.id)
        reply = await self.ai_answer(message, system_prompt=prompt, temperature=temp)
        await ctx.send(reply)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot's own messages to prevent infinite loops
        if message.author.bot or not message.guild:
            return
            
        ai_channel_id, personality, temp = await self._fetch_ai_settings(message.guild.id)
        
        is_mentioned = self.bot.user in message.mentions
        is_ai_channel = ai_channel_id and message.channel.id == ai_channel_id

        # If not mentioned AND not in the AI channel, ignore
        if not is_mentioned and not is_ai_channel:
            return
            
        # Ignore messages that are explicitly bot commands
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        async with message.channel.typing():
            # Build memory buffer from 10 previous messages
            history = []
            try:
                import re
                async for msg in message.channel.history(limit=10, before=message):
                    if msg.content:
                        # Decide if "user" or "assistant" role
                        role = "assistant" if msg.author.id == self.bot.user.id else "user"
                        clean_hist = re.sub(r'<@!?&?\d+>', '', msg.content).strip()
                        if clean_hist:
                            # Prefix with the user's name so the AI knows who is talking
                            final_content = clean_hist if role == "assistant" else f"[{msg.author.display_name}]: {clean_hist}"
                            history.append({"role": role, "content": final_content})
                        
                # History is fetched newest first, we must reverse it to chronological order
                history.reverse()
            except discord.Forbidden:
                pass

            import re
            clean_prompt = re.sub(r'<@!?&?\d+>', '', message.content).strip()
            if not clean_prompt:
                clean_prompt = "Hello"

            reply = await self.ai_answer(
                clean_prompt, 
                system_prompt=personality, 
                temperature=temp, 
                message_history=history
            )
            await message.reply(reply)


async def setup(bot: commands.Bot):
    await bot.add_cog(AICog(bot))
