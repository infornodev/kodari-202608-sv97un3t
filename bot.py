import logging
import os
import re
from datetime import timedelta

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from giveaway_manager import GiveawayManager


load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("giveaway-bot")

GIVEAWAY_EMOJI = "🎉"
DURATION_PART = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
manager = GiveawayManager()


def parse_duration(value: str) -> timedelta | None:
    value = value.strip().lower()
    parts = list(DURATION_PART.finditer(value))
    if not parts or "".join(part.group(0).replace(" ", "") for part in parts) != value.replace(" ", ""):
        return None

    seconds = 0
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    for part in parts:
        seconds += int(part.group(1)) * multipliers[part.group(2)]
    return timedelta(seconds=seconds) if seconds > 0 else None


def giveaway_embed(giveaway: dict) -> discord.Embed:
    active = giveaway["status"] == "active"
    embed = discord.Embed(
        title=f"🎉 {giveaway['prize']}",
        description=(
            f"React with {GIVEAWAY_EMOJI} to enter!\n"
            "Each person gets one normal entry. Server staff can grant bonus entries."
            if active
            else "This giveaway has ended."
        ),
        color=discord.Color.green() if active else discord.Color.blurple(),
    )
    embed.add_field(name="Giveaway ID", value=f"`{giveaway['id']}", inline=True)
    embed.add_field(name="Winners", value=str(giveaway["winner_count"]), inline=True)
    embed.add_field(name="Host", value=f"<@{giveaway['host_id']}>", inline=True)

    ends_at = discord.utils.parse_time(giveaway["ends_at"])
    if active and ends_at:
        embed.add_field(name="Ends", value=discord.utils.format_dt(ends_at, "R"), inline=False)
    elif giveaway["winner_ids"]:
        mentions = " ".join(f"<@{user_id}>" for user_id in giveaway["winner_ids"])
        embed.add_field(name="Winner(s)", value=mentions, inline=False)
    else:
        embed.add_field(name="Result", value="No valid entries.", inline=False)
    embed.set_footer(text="Use the Giveaway ID with the admin commands.")
    return embed


async def giveaway_message(giveaway: dict) -> discord.Message | None:
    if not giveaway.get("message_id"):
        return None
    channel = bot.get_channel(int(giveaway["channel_id"]))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(giveaway["channel_id"]))
        except discord.HTTPException:
            return None
    try:
        return await channel.fetch_message(int(giveaway["message_id"]))
    except (discord.HTTPException, discord.NotFound):
        return None


async def reaction_participants(giveaway: dict) -> list[int]:
    message = await giveaway_message(giveaway)
    if message is None:
        return []

    for reaction in message.reactions:
        if str(reaction.emoji) != GIVEAWAY_EMOJI:
            continue
        users = []
        async for user in reaction.users(limit=None):
            if not user.bot:
                users.append(user.id)
        return users
    return []


async def announce_result(giveaway: dict) -> None:
    message = await giveaway_message(giveaway)
    if message is not None:
        try:
            await message.edit(embed=giveaway_embed(giveaway))
        except discord.HTTPException:
            logger.exception("Unable to update giveaway message %s", giveaway["id"])

    channel = bot.get_channel(int(giveaway["channel_id"]))
    if channel is None:
        return
    if giveaway["winner_ids"]:
        winners = " ".join(f"<@{user_id}>" for user_id in giveaway["winner_ids"])
        await channel.send(f"🎉 Giveaway **{giveaway['prize']}** ended! Winner(s): {winners}")
    else:
        await channel.send(f"The giveaway **{giveaway['prize']}** ended with no valid entries.")


async def end_giveaway(giveaway_id: str, excluded_ids: list[int] | None = None) -> dict | None:
    giveaway = manager.get(giveaway_id)
    if giveaway is None or giveaway["status"] != "active":
        return None
    participants = await reaction_participants(giveaway)
    winners = manager.choose_winners(giveaway_id, participants, excluded_ids)
    finished = manager.finish(giveaway_id, winners)
    if finished:
        await announce_result(finished)
    return finished


@tasks.loop(seconds=15)
async def finish_expired_giveaways() -> None:
    for giveaway in manager.due():
        await end_giveaway(giveaway["id"])


@finish_expired_giveaways.before_loop
async def before_expiry_loop() -> None:
    await bot.wait_until_ready()


@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
    if not finish_expired_giveaways.is_running():
        finish_expired_giveaways.start()


@bot.group(name="giveaway", aliases=["gw"], invoke_without_command=True)
@commands.guild_only()
async def giveaway(ctx: commands.Context) -> None:
    await ctx.send(
        "**Giveaway commands**\n"
        "`!giveaway create <duration> <winners> <prize>`\n"
        "`!giveaway info <id>`\n"
        "`!giveaway addentries <id> @user <amount>` *(Manage Server)*\n"
        "`!giveaway end <id>` *(Manage Server)*\n"
        "`!giveaway reroll <id>` *(Manage Server)*\n"
        "`!giveaway setwinner <id> @user [@user...]` *(Manage Server)*\n"
        "Durations support `s`, `m`, `h`, `d`, and `w`, for example `2h30m`."
    )


@giveaway.command(name="create")
@commands.guild_only()
async def create_giveaway(ctx: commands.Context, duration: str, winner_count: int, *, prize: str) -> None:
    if not 1 <= winner_count <= 20:
        await ctx.send("Winner count must be between 1 and 20.")
        return
    length = parse_duration(duration)
    if length is None or length > timedelta(days=30):
        await ctx.send("Use a duration such as `30m`, `2h`, or `2h30m` (maximum 30 days).")
        return
    if not prize.strip():
        await ctx.send("A prize is required.")
        return

    ends_at = discord.utils.utcnow() + length
    record = manager.create(ctx.guild.id, ctx.channel.id, ctx.author.id, prize.strip(), winner_count, ends_at)
    message = await ctx.send(embed=giveaway_embed(record), content=f"React with {GIVEAWAY_EMOJI} to enter!")
    try:
        await message.add_reaction(GIVEAWAY_EMOJI)
    except discord.HTTPException:
        await ctx.send("I created the giveaway, but I could not add the entry reaction. Check my permissions.")
    manager.attach_message(record["id"], message.id)
    await ctx.send(f"Giveaway created with ID `{record['id']}`.")


@giveaway.command(name="info")
@commands.guild_only()
async def giveaway_info(ctx: commands.Context, giveaway_id: str) -> None:
    record = manager.get(giveaway_id)
    if record is None or record["guild_id"] != str(ctx.guild.id):
        await ctx.send("That giveaway was not found.")
        return
    await ctx.send(embed=giveaway_embed(record))


@giveaway.command(name="addentries", aliases=["boost", "entries"])
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def add_entries(ctx: commands.Context, giveaway_id: str, member: discord.Member, amount: int) -> None:
    record = manager.get(giveaway_id)
    if record is None or record["guild_id"] != str(ctx.guild.id):
        await ctx.send("That giveaway was not found.")
        return
    if not 1 <= amount <= 1000:
        await ctx.send("Bonus entries must be between 1 and 1,000.")
        return
    updated = manager.add_bonus_entries(giveaway_id, member.id, amount)
    if updated is None:
        await ctx.send("That giveaway is already over.")
        return
    await ctx.send(f"Added **{amount}** weighted bonus entries for {member.mention}.")


@giveaway.command(name="end")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def end_command(ctx: commands.Context, giveaway_id: str) -> None:
    record = manager.get(giveaway_id)
    if record is None or record["guild_id"] != str(ctx.guild.id):
        await ctx.send("That giveaway was not found.")
        return
    if record["status"] != "active":
        await ctx.send("That giveaway has already ended.")
        return
    await end_giveaway(giveaway_id)


@giveaway.command(name="reroll")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def reroll_command(ctx: commands.Context, giveaway_id: str) -> None:
    record = manager.get(giveaway_id)
    if record is None or record["guild_id"] != str(ctx.guild.id):
        await ctx.send("That giveaway was not found.")
        return
    if record["status"] != "ended":
        await ctx.send("End the giveaway before rerolling it.")
        return
    participants = await reaction_participants(record)
    winners = manager.choose_winners(giveaway_id, participants, record["winner_ids"])
    updated = manager.finish(giveaway_id, winners)
    if updated:
        await announce_result(updated)


@giveaway.command(name="setwinner")
@commands.guild_only()
@commands.has_guild_permissions(manage_guild=True)
async def set_winner(
    ctx: commands.Context,
    giveaway_id: str,
    members: commands.Greedy[discord.Member],
) -> None:
    record = manager.get(giveaway_id)
    if record is None or record["guild_id"] != str(ctx.guild.id):
        await ctx.send("That giveaway was not found.")
        return
    if record["status"] != "active":
        await ctx.send("That giveaway has already ended.")
        return
    if not members:
        await ctx.send("Mention at least one winner.")
        return
    if len(members) > record["winner_count"]:
        await ctx.send(f"This giveaway allows only {record['winner_count']} winner(s).")
        return
    updated = manager.finish(giveaway_id, [member.id for member in members])
    if updated:
        await announce_result(updated)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need the **Manage Server** permission to use that command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Missing an argument. Use `!giveaway` to see the command format.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("I could not understand one of the arguments. Mention users where required.")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("Giveaways can only be managed inside a server.")
    else:
        logger.exception("Unhandled command error", exc_info=error)
        await ctx.send("Something went wrong while processing that command.")


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and add your bot token.")

bot.run(token)