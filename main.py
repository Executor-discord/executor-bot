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
pending = None              # (guild, action, payload)
expire_task = None
erased_roles = {}           # {guild_id: role_backup}

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

async def expire_confirmation():
    global pending
    await asyncio.sleep(CONFIRM_TIMEOUT)
    if pending:
        guild, action, _ = pending
        await log_event(guild, f"⌛ CONFIRMATION EXPIRED: {action}")
        pending = None

# =========================
# READY / PRESENCE
# =========================
@bot.event
async def on_ready():
    await bot.change_presence(
        status=discord.Status.dnd,
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="Every Move"
        )
    )
    print("Monitoring enabled.")
    for g in bot.guilds:
        await log_event(g, "🟢 EXECUTOR ONLINE")

# =========================
# AUTO-LEAVE UNAUTHORIZED
# =========================
@bot.event
async def on_guild_join(guild):
    await log_event(guild, f"⚠️ Joined server: {guild.name} ({guild.id})")
    if guild.owner_id != OWNER_ID:
        await log_event(guild, "🚫 Unauthorized server. Leaving.")
        await guild.leave()

# =========================
# MESSAGE HANDLER
# =========================
@bot.event
async def on_message(message):
    global pending, expire_task

    if message.author.bot:
        return

    # =====================
    # DM CONFIRMATION
    # =====================
    if isinstance(message.channel, discord.DMChannel):
        if message.content.lower() == "confirm" and pending:
            guild, action, payload = pending
            pending = None
            if expire_task:
                expire_task.cancel()

            await log_event(guild, f"✅ CONFIRMED: {action}")

            if action in ("lockdown", "panic"):
                for ch in guild.channels:
                    ow = ch.overwrites_for(guild.default_role)
                    ow.send_messages = False
                    await ch.set_permissions(guild.default_role, overwrite=ow)

            elif action == "unlock":
                for ch in guild.channels:
                    ow = ch.overwrites_for(guild.default_role)
                    ow.send_messages = None
                    await ch.set_permissions(guild.default_role, overwrite=ow)

            elif action == "terminate":
                for g in list(bot.guilds):
                    await log_event(g, "💀 EXTINCTION EVENT")
                    await g.leave()
                await bot.close()
                sys.exit(0)

            elif action == "exile":
                await payload.ban(reason="Exiled by EXECUTOR")

            elif action == "eject":
                await payload.kick(reason="Ejected by EXECUTOR")

            elif action == "silence":
                until = datetime.now(timezone.utc) + timedelta(days=28)
                await payload.timeout(until, reason="Silenced by EXECUTOR")

            elif action == "purge":
                channel, amount = payload
                await channel.purge(limit=min(amount + 1, 101))

            elif action == "reverse":
                data = erased_roles.get(guild.id)
                if data:
                    await guild.create_role(
                        name=data["name"],
                        permissions=data["permissions"],
                        color=data["color"],
                        hoist=data["hoist"],
                        mentionable=data["mentionable"]
                    )

            elif action == "recall":
                user = await bot.fetch_user(payload)
                await guild.unban(user)

        return

    # =====================
    # SERVER COMMANDS
    # =====================
    content = message.content.lower()
    guild = message.guild

    # ---- ERASE ROLE ----
    if content.startswith("erase ") and is_owner(message.author):
        arg = message.content[6:].strip()
        role = (
            message.role_mentions[0]
            if message.role_mentions
            else discord.utils.find(lambda r: r.name.lower() == arg.lower(), guild.roles)
        )

        if role and not role.is_default() and role < guild.me.top_role:
            erased_roles[guild.id] = {
                "name": role.name,
                "permissions": role.permissions,
                "color": role.color,
                "hoist": role.hoist,
                "mentionable": role.mentionable
            }
            await role.delete(reason="Erased by EXECUTOR")
            await log_event(guild, f"🗑️ ROLE ERASED: {role.name}")

        await message.delete()
        return

    # ---- POWER COMMANDS ----
    if content.startswith(POWER_PREFIX) and is_owner(message.author):
        parts = message.content[len(POWER_PREFIX):].split()
        action = parts[0].lower()
        payload = None

        if action in ("exile", "eject", "silence") and message.mentions:
            payload = message.mentions[0]
        elif action == "purge" and len(parts) == 2 and parts[1].isdigit():
            payload = (message.channel, int(parts[1]))
        elif action == "recall" and len(parts) == 2 and parts[1].isdigit():
            payload = int(parts[1])

        pending = (guild, action, payload)
        expire_task = asyncio.create_task(expire_confirmation())

        await message.author.send(
            f"⚠️ `{action.upper()}` armed.\nReply **confirm** within {CONFIRM_TIMEOUT}s."
        )
        await log_event(guild, f"⚠️ {action.upper()} ARMED")
        await message.delete()
        return

    await bot.process_commands(message)

# =========================
# RUN
# =========================
bot.run(TOKEN)

