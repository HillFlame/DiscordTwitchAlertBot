import discord
from discord.ext import commands, tasks
from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
import asyncio
import json
import os
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')

# Set up logging
logging.basicConfig(level=logging.INFO, filename='bot.log',
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

logger = logging.getLogger('discord_bot')

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

twitch = None

async def setup_twitch():
    global twitch
    twitch = await Twitch(TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
    await twitch.authenticate_app([])

# Run the setup function
asyncio.run(setup_twitch())

# Function to save data to a JSON file
def save_data(data, filename='data.json'):
    with open(filename, 'w') as f:
        json.dump(data, f)
    logger.info('Data saved to %s', filename)

# Function to load data from a JSON file
def load_data(filename='data.json'):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            logger.info('Data loaded from %s', filename)
            return json.load(f)
    return {}

# Load previous data
streamer_role_dict = load_data()

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user.name}')
    await asyncio.sleep(5)  # Wait to ensure the bot is fully ready
    for guild in bot.guilds:
        logger.info(f"Bot is in guild: {guild.name} (ID: {guild.id})")
    check_streamer_status.start()

@tasks.loop(minutes=1)
async def check_streamer_status():
    for guild_id, alerts in streamer_role_dict.items():
        logger.info(f"Checking alerts for guild ID: {guild_id}")
        guild = bot.get_guild(guild_id)
        if guild is None:
            logger.error(f"Guild {guild_id} not found")
            continue

        for alert in alerts[:]:  # Create a copy of the list to avoid modifying it while iterating
            streamer = alert['streamer']
            role_id = alert['role']

            user_info = await first(twitch.get_users(logins=[streamer]))
            if user_info:
                user_id = user_info.id
                profile_image_url = user_info.profile_image_url
                stream_info = await first(twitch.get_streams(user_id=[user_id]))

                if stream_info and stream_info.type == 'live':
                    channel = guild.get_channel(alert.get('channel', guild.system_channel.id))
                    if channel:
                        embed = discord.Embed(
                            title="Stream Alert!",
                            description=f"[{streamer} is now live on Twitch!](https://www.twitch.tv/{streamer})",
                            color=discord.Color.blurple()
                        )
                        embed.set_thumbnail(url=profile_image_url)
                        await channel.send(content=guild.get_role(role_id).mention, embed=embed)
                        logger.info(f"Alert sent for streamer {streamer} in guild {guild_id}")

                        # Remove the alert from the list
                        alerts.remove(alert)

        # Save the updated list of alerts for the guild
        streamer_role_dict[guild_id] = alerts
        save_data(streamer_role_dict)

@bot.command()
async def set_alert(ctx):
    def check(message):
        return message.author == ctx.author and message.channel == ctx.channel

    await ctx.send(embed=discord.Embed(
        title="Set Alert",
        description="Please enter the Twitch streamer you want to set an alert for:",
        color=discord.Color.blurple()
    ))
    msg = await bot.wait_for('message', check=check)
    streamer = msg.content

    await ctx.send(embed=discord.Embed(
        title="Set Alert",
        description="Please mention the role you want to ping when the streamer goes live:",
        color=discord.Color.blurple()
    ))
    msg = await bot.wait_for('message', check=check)
    if not msg.raw_role_mentions:
        await ctx.send(embed=discord.Embed(
            title="Error",
            description="No role mentioned. Please mention a valid role.",
            color=discord.Color.red()
        ))
        return

    role_id = int(msg.raw_role_mentions[0])

    user_info = await first(twitch.get_users(logins=[streamer]))
    if not user_info:
        await ctx.send(embed=discord.Embed(
            title="Error",
            description="Streamer not found. Please check the username and try again.",
            color=discord.Color.red()
        ))
        return

    guild_alerts = streamer_role_dict.get(ctx.guild.id, [])
    guild_alerts.append({'streamer': streamer, 'role': role_id})
    streamer_role_dict[ctx.guild.id] = guild_alerts
    save_data(streamer_role_dict)

    await ctx.send(embed=discord.Embed(
        title="Alert Set",
        description=f"Alert set for {streamer}. Will ping {ctx.guild.get_role(role_id).mention} when they go live.",
        color=discord.Color.green()
    ))

    # Check if the streamer is already live
    user_id = user_info.id
    profile_image_url = user_info.profile_image_url
    stream_info = await first(twitch.get_streams(user_id=[user_id]))

    if stream_info and stream_info.type == 'live':
        channel = ctx.guild.get_channel(guild_alerts[-1].get('channel', ctx.guild.system_channel.id))
        if channel:
            embed = discord.Embed(
                title="Stream Alert!",
                description=f"[{streamer} is already live on Twitch!](https://www.twitch.tv/{streamer})",
                color=discord.Color.blurple()
            )
            embed.set_thumbnail(url=profile_image_url)
            await channel.send(content=ctx.guild.get_role(role_id).mention, embed=embed)

@bot.command()
async def remove_alert(ctx):
    guild_id = ctx.guild.id

    if guild_id not in streamer_role_dict:
        await ctx.send(embed=discord.Embed(
            title="Error",
            description="There are no alerts set for this server.",
            color=discord.Color.red()
        ))
        return

    alerts = streamer_role_dict[guild_id]
    alert_list = "\n".join([f"{i+1}. {alert['streamer']}" for i, alert in enumerate(alerts)])

    await ctx.send(embed=discord.Embed(
        title="Alerts",
        description=alert_list,
        color=discord.Color.blurple()
    ))

    def check(message):
        return message.author == ctx.author and message.channel == ctx.channel

    await ctx.send(embed=discord.Embed(
        title="Remove Alert",
        description="Please enter the number of the alert you want to remove:",
        color=discord.Color.blurple()
    ))
    msg = await bot.wait_for('message', check=check)
    alert_index = int(msg.content) - 1

    if alert_index < 0 or alert_index >= len(alerts):
        await ctx.send(embed=discord.Embed(
            title="Error",
            description="Invalid alert number. Please try again.",
            color=discord.Color.red()
        ))
        return

    removed_alert = alerts.pop(alert_index)
    if not alerts:
        del streamer_role_dict[guild_id]
    else:
        streamer_role_dict[guild_id] = alerts
    save_data(streamer_role_dict)

    await ctx.send(embed=discord.Embed(
        title="Alert Removed",
        description=f"Alert for {removed_alert['streamer']} removed.",
        color=discord.Color.green()
    ))

@bot.command()
async def channel_set(ctx):
    def check(message):
        return message.author == ctx.author and message.channel == ctx.channel

    await ctx.send(embed=discord.Embed(
        title="Set Channel",
        description="Please mention the channel where you want the announcements to be sent:",
        color=discord.Color.blurple()
    ))
    msg = await bot.wait_for('message', check=check)
    if not msg.raw_channel_mentions:
        await ctx.send(embed=discord.Embed(
            title="Error",
            description="No channel mentioned. Please mention a valid channel.",
            color=discord.Color.red()
        ))
        return

    channel_id = int(msg.raw_channel_mentions[0])

    guild_data = streamer_role_dict.get(ctx.guild.id, {})
    guild_data['channel'] = channel_id
    streamer_role_dict[ctx.guild.id] = guild_data
    save_data(streamer_role_dict)

    await ctx.send(embed=discord.Embed(
        title="Channel Set",
        description=f"Announcements will be sent to {ctx.guild.get_channel(channel_id).mention}.",
        color=discord.Color.green()
    ))

# Run the bot
bot.run(DISCORD_TOKEN)
