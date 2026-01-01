import os
import sys
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from flask import Flask
from threading import Thread

# =========================
# CONFIG
# =========================
OWNER_ID = 1023468164304097381
LOG_CHANNEL_ID = 1455212828947644579
BOT_NAME = "EXECUTOR"

POWER_PREFIX = "ex "
CONFIRM_TIMEOUT = 30

app = Flask(__name__)
port = int(os.environ.get("PORT", 8080))

@app.route("/")
def home():
    return "alive"

def run_web():
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web).start()

# =========================
# ENV
# =========================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing")

# =========================
# BOT SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="", intents=intents, help_command=None)

# =========================
# STATE
# =========================
pending = None
expire_task = None
erased_roles = {}

# =========================
# UTILS
# =========================
def is_owner(user):
    return user.id == OWNER_ID

async def log_event(guild, text):
    if not guild:
        return
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        await ch.send(f"`[{ts}]` {text}")

async def expire_confirmation(channel):
    global pending
    await asyncio.sleep(CONFIRM_TIMEOUT)
    if pending:
        await channel.send("⌛ Confirmation expired.", delete_after=5)
        pending = None

async def private_notice(channel, text):
    await channel.send(f"👁️ {text}", delete_after=5)

# =========================
# READY
# =========================
@bot.event
async def on_ready():
    await bot.change_presence(
        status=discord.Status.dnd,
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="everything"
        )
    )
    print("EXECUTOR ONLINE")
    for g in bot.guilds:
        await log_event(g, "🟢 EXECUTOR ONLINE")

# =========================
# MESSAGE HANDLER
# =========================
@bot.event
async def on_message(message):
    global pending, expire_task

    if message.author.bot:
        return

    content = message.content.lower()
    guild = message.guild

    # =====================
    # CONFIRM IN CHAT
    # =====================
    if content == "confirm" and pending and is_owner(message.author):
        action, payload, channel = pending
        pending = None
        if expire_task:
            expire_task.cancel()

        await private_notice(channel, f"Confirmed `{action}`")
        await log_event(guild, f"✅ CONFIRMED: {action}")

        if action == "exile":
            member, reason = payload
            await member.ban(reason=reason)

        elif action == "eject":
            member, reason = payload
            await member.kick(reason=reason)

        elif action == "silence":
            member, duration, reason = payload
            until = datetime.now(timezone.utc) + duration
            await member.timeout(until, reason=reason)

        elif action == "erase_role":
            role = payload
            erased_roles[guild.id] = {
                "name": role.name,
                "permissions": role.permissions,
                "color": role.color,
                "hoist": role.hoist,
                "mentionable": role.mentionable
            }
            await role.delete(reason="Erased by EXECUTOR")

        elif action == "erase_msgs":
            target, channel, count = payload
            deleted = []
            async for msg in channel.history(limit=200):
                if msg.author == target:
                    deleted.append(msg)
                if len(deleted) >= count:
                    break
            if deleted:
                await channel.delete_messages(deleted)

        return

    # =====================
    # ERASE ROLE (CONFIRM)
    # =====================
    if content.startswith("erase ") and is_owner(message.author) and not message.reference:
        arg = message.content[6:].strip()
        role = (
            message.role_mentions[0]
            if message.role_mentions
            else discord.utils.find(lambda r: r.name.lower() == arg.lower(), guild.roles)
        )

        if role and not role.is_default():
            pending = ("erase_role", role, message.channel)
            expire_task = asyncio.create_task(expire_confirmation(message.channel))
            await private_notice(message.channel, f"Confirm erase role `{role.name}`")

        await message.delete()
        return

    # =====================
    # ERASE MESSAGES (REPLY ONLY)
    # =====================
    if content.startswith("erase ") and is_owner(message.author) and message.reference:
        if not content.split()[1].isdigit():
            return

        count = int(content.split()[1])
        replied = await message.channel.fetch_message(message.reference.message_id)
        target = replied.author

        pending = ("erase_msgs", (target, message.channel, count), message.channel)
        expire_task = asyncio.create_task(expire_confirmation(message.channel))
        await private_notice(message.channel, f"Confirm erase {count} msgs from `{target}`")
        await message.delete()
        return

    # =====================
    # POWER COMMANDS
    # =====================
    if content.startswith(POWER_PREFIX) and is_owner(message.author):
        parts = message.content[len(POWER_PREFIX):].split()
        action = parts[0]

        if action in ("exile", "eject") and message.mentions:
            reason = " ".join(parts[2:]) if len(parts) > 2 else "No reason"
            pending = (action, (message.mentions[0], reason), message.channel)

        elif action == "silence" and message.mentions:
            duration = timedelta(minutes=int(parts[2])) if len(parts) > 2 else timedelta(hours=1)
            reason = " ".join(parts[3:]) if len(parts) > 3 else "No reason"
            pending = ("silence", (message.mentions[0], duration, reason), message.channel)

        expire_task = asyncio.create_task(expire_confirmation(message.channel))
        await private_notice(message.channel, f"`{action}` armed. Type `confirm`.")
        await message.delete()
        return

    # =====================
    # PING
    # =====================
    if content == "ping":
        await private_notice(message.channel, f"Pong `{round(bot.latency * 1000)}ms`")

    await bot.process_commands(message)

# =========================
# RUN
# =========================
bot.run(TOKEN)
