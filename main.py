import discord
from discord.ext import commands
import slack_sdk
from slackeventsapi import SlackEventAdapter
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import json
import os
import threading
import asyncio
import concurrent.futures
import functools
import sqlite3


print("REMEMBER TO START NGROK")


dbot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
discord_server_id = 1301317329333784668
main_discord_server_object = None
allowed_channels = ["hackclub-discord-bridge-management"] # Blank means all channel are allowed, this had to be added because of hack club things

sclient = WebClient(token=open("slack_token", "r").read())
SLACK_SIGNING_SECRET = open("slack_signing_secret", "r").read()
slack_events_adapter = SlackEventAdapter(SLACK_SIGNING_SECRET, endpoint="/slack/events")

database_name = "main.db"

with sqlite3.connect(database_name) as conn:
    print("did the thing")

try:
    with open("./discord_to_slack_channel.json", "r+") as the_file:
        dc_to_sc = json.load(the_file)
except json.decoder.JSONDecodeError as e:
    print(e)
    with open("./discord_to_slack_channel.json", "w+") as the_file:
        the_file.write("{}")
        dc_to_sc = {}

sc_to_dc = {v: k for k, v in dc_to_sc.items()} # Swap the discord to slack channel dictionary around so that a discord channel can be looked up from the slack channel


def try_setup_sql_first_time():
    messages_table_statement = """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unix_timestamp INT NOT NULL,
        
        message_text TEXT NOT NULL,
        slack_message_ts TEXT NOT NULL,
        discord_message_id INT NOT NULL,
        slack_thread_ts TEXT not null,
        slack_channel_id TEXT NOT NULL,
        discord_channel_id INT NOT NULL,
        slack_author_id TEXT NOT NULL,
        discord_author_id INT NOT NULL
    )
    """

    channels_table_statement = """
    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        
        slack_channel_id TEXT NOT NULL,
        discord_channel_id INT NOT NULL,
        is_thread INT NOT NULL,
        slack_thread_ts TEXT NOT NULL,
        send_to_slack_allowed INT NOT NULL,
        communicate_allowed INT NOT NULL
    )
    """

    try:
        with sqlite3.connect(database_name) as conn:
            cursor = conn.cursor()
            cursor.execute(messages_table_statement) # Create the table of messages if it doesn't exist
            cursor.execute(channels_table_statement) # Create the table of channels if it doesn't exist

            conn.commit()
            print("Yay made the tables")
    except sqlite3.OperationalError as e:
        print("Failed to create tables:", e)

#def db_add_message(slack_message_data, discord_channel_id, discord_message_id):


def refresh_channel_cache_file():
    sc_to_dc = {v: k for k, v in dc_to_sc.items()}
    with open("./discord_to_slack_channel.json", "w+") as the_file:  # Save the cache to a file
        json.dump(dc_to_sc, the_file)

def get_slack_channel_name(channel_id):
    try:
        response = sclient.conversations_info(channel=channel_id)
        channel_name = response['channel']['name']
        return channel_name
    except SlackApiError as e:
        print(f"Error fetching channel info: {e.response['error']}")
        return None

def get_slack_channel_id(channel_name):
    try:
        for result in sclient.conversations_list():
            for channel in result['channels']:
                if channel['name'] == channel_name:
                    return channel['id']
        return None
    except SlackApiError as e:
        print(f"Error fetching channel info: {e.response['error']}")
        print(e.response.headers["Retry-After"])
        return None

def get_discord_channel_object_from_name(channel_name):
    return discord.utils.get(main_discord_server_object.channels, name=channel_name)

def get_discord_channel_object_from_id(channel_id):
    return discord.utils.get(main_discord_server_object.channels, id=channel_id)

def slack_channel_to_discord_channel(slack_channel_id):
    global sc_to_dc
    global dc_to_sc
    try: # Try get the id from a cache
        return sc_to_dc[str(slack_channel_id)]
    except KeyError:
        slack_chan_name = get_slack_channel_name(slack_channel_id)
        if not (allowed_channels == None or slack_chan_name in allowed_channels):
            return None
        discord_channel = get_discord_channel_object_from_name(slack_chan_name)
        if discord_channel == None:
            return None
        dc_to_sc[str(discord_channel.id)] = slack_channel_id
        refresh_channel_cache_file()
        return discord_channel.id

def discord_channel_to_slack_channel(discord_channel_id):
    global dc_to_sc
    global sc_to_dc
    try: # Try get the id from a cache
        return dc_to_sc[str(discord_channel_id)]
    except KeyError:
        discord_channel = get_discord_channel_object_from_id(discord_channel_id)
        if discord_channel == None:
            return
        discord_chan_name = discord_channel.name
        if not (allowed_channels == None or discord_chan_name in allowed_channels):
            return
        slack_channel_id = get_slack_channel_id(discord_chan_name)
        if slack_channel_id == None:
            return None
        dc_to_sc[str(discord_channel_id)] = slack_channel_id
        refresh_channel_cache_file()
        return slack_channel_id

async def send_with_webhook(discord_channel_id, message, username, avatar_url):
    channel = dbot.get_channel(discord_channel_id)
    webhooks = await channel.webhooks()
    webhook = None
    if webhooks:
        for wh in webhooks:
            print(wh)
            if wh.user.id == dbot.user.id:
                webhook = wh
                break
    if not webhook:
        print(f"Creating new webhook in #{channel.name}")
        webhook = await channel.create_webhook(name="Slack Link")
    print(f"Sending message to {webhook}: {message}, {username}, {avatar_url}")
    return await webhook.send(content=message, username=username, avatar_url=avatar_url, wait=True)



@slack_events_adapter.on("reaction_added")
def reaction_added(event_data):
    emoji = event_data["event"]["reaction"]
    print(emoji)

@slack_events_adapter.on("message") # Slack message listening, send to discord
def handle_message(event_data):
    message = event_data["event"]

    if message.get("subtype") is None:
        print(message)
        print(event_data)
        try:
            user_info = sclient.users_info(user=message["user"])["user"]
            display_name = user_info["profile"]["display_name"]
            try:
                avatar_url = user_info["profile"]["image_original"]
            except KeyError:
                avatar_url = user_info["profile"]["image_512"]
        except SlackApiError as e:
            print(f"Error getting user profile info: {e}")
            display_name = "Anon"
            avatar_url = "https://cloud-mixfq3elm-hack-club-bot.vercel.app/0____.png"
        discord_channel = slack_channel_to_discord_channel(message["channel"])
        if discord_channel is None:
            print("Discord channel not found")
            return
        #db_add_message(slack_message_data=message, discord_channel_id=discord_channel.id)
        sent_discord_message_object = asyncio.run_coroutine_threadsafe(send_with_webhook(message=message["text"], username=display_name, avatar_url=avatar_url,
                              discord_channel_id=int(discord_channel)), dbot.loop)
        messages_insert_statement = f"""
        INSERT INTO messages(message_text, slack_message_ts, discord_message_id, slack_channel_id, discord_channel_id, slack_thread_ts, slack_author_id, discord_author_id)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """
        with sqlite3.connect(database_name) as conn:
            cursor = conn.cursor()
            cursor.execute(messages_insert_statement, (message["text"], message["ts"], sent_discord_message_object.id, ))



@dbot.event
async def on_ready():
    global main_discord_server_object
    print('Logged on as', dbot.user)
    main_discord_server_object = dbot.get_guild(discord_server_id)
    print(slack_channel_to_discord_channel("C0P5NE354"))

@dbot.event
async def on_message(message): # Discord message listening, send to slack
    # don't respond to ourselves
    if message.author == dbot.user:
        return
    elif message.webhook_id != None: # Don't repost messages from the webhook
        return
    elif message.channel.type in ["public_thread", "private_thread"]:
        message.reply("Sorry, threads aren't supported yet!")
        return
    elif message.guild.id == discord_server_id:
        slack_channel_id = await dbot.loop.run_in_executor(None, functools.partial(discord_channel_to_slack_channel, message.channel.id))
        #print(2)
        if slack_channel_id == None:
            return
        try:
            await dbot.loop.run_in_executor(None, functools.partial(sclient.chat_postMessage, channel=slack_channel_id, text=message.content, username=message.author.display_name, icon_url=message.author.avatar.url)) # , thread_ts="1730500285.549289"
        except SlackApiError as e:
            print(f"Error sending message to slack: {e}")

#slack_events_adapter.start(port=3000)
slack_thread = threading.Thread(target=slack_events_adapter.start, kwargs={'port': 3000})
slack_thread.start()

intents = discord.Intents.all()
intents.message_content = True
dbot.run(open("discord_token", "r").read())