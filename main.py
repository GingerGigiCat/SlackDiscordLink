import discord
from discord.ext import commands

#import slack_sdk
#from slackeventsapi import SlackEventAdapter
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.error import *


import json
import os
import threading
import asyncio
import concurrent.futures
import functools
import sqlite3


dbot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
discord_server_id = 1301317329333784668
main_discord_server_object = None
allowed_mentions = discord.AllowedMentions(roles=False, everyone=False)
allowed_channels = ["hackclub-discord-bridge-management"] # Blank means all channel are allowed, this had to be added because of hack club things

with open("slack_bot_token", "r") as token_f:
    with open("slack_signing_secret", "r") as signing_secret_f:
        sapp = AsyncApp(token=token_f.read(), signing_secret=signing_secret_f.read())

#sclient = WebClient(token=open("slack_bot_token", "r").read())
#SLACK_SIGNING_SECRET = open("slack_signing_secret", "r").read()
#slack_events_adapter = SlackEventAdapter(SLACK_SIGNING_SECRET, endpoint="/slack/events")

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
        
        slack_message_ts TEXT NOT NULL,
        discord_message_id INT NOT NULL,
        slack_thread_ts TEXT,
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

async def db_add_message(s_message_data, d_message_object, source="slack"):
    messages_insert_statement = f"""
    INSERT INTO messages(slack_message_ts, discord_message_id, slack_channel_id, discord_channel_id, slack_thread_ts, slack_author_id, discord_author_id)
    VALUES(?, ?, ?, ?, ?, ?, ?)
    """
    try:
        slack_thread_ts = s_message_data["slack_thread_ts"]
    except KeyError:
        slack_thread_ts = ""
    with sqlite3.connect(database_name) as conn:
        cursor = conn.cursor()
        if source == "slack":
            d_message_object.author.id = 0
            cursor.execute(messages_insert_statement, (s_message_data["ts"], d_message_object.id, s_message_data["channel"], d_message_object.channel.id, slack_thread_ts, s_message_data["user"], 0))
        elif source == "discord":
            cursor.execute(messages_insert_statement, (s_message_data["message"]["ts"], d_message_object.id, s_message_data["channel"], d_message_object.channel.id, slack_thread_ts, "no", d_message_object.author.id))
        conn.commit()

async def refresh_channel_cache_file():
    sc_to_dc = {v: k for k, v in dc_to_sc.items()}
    with open("./discord_to_slack_channel.json", "w+") as the_file:  # Save the cache to a file
        json.dump(dc_to_sc, the_file)

async def get_slack_channel_name(channel_id):
    sclient = sapp.client
    try:
        response = await sclient.conversations_info(channel=channel_id)
        channel_name = response['channel']['name']
        return channel_name
    except BoltError as e:
        print(f"Error fetching channel info: {e}")
        return None

async def get_slack_channel_id(channel_name):
    sclient = sapp.client
    try:
        for result in await sclient.conversations_list():
            for channel in result['channels']:
                if channel['name'] == channel_name:
                    return channel['id']
        return None
    except BoltError as e:
        print(f"Error fetching channel info: {e}")
        #print(e.response.headers["Retry-After"])
        return None

async def get_discord_channel_object_from_name(channel_name):
    return discord.utils.get(main_discord_server_object.channels, name=channel_name)

async def get_discord_channel_object_from_id(channel_id):
    return discord.utils.get(main_discord_server_object.channels, id=channel_id)

async def slack_channel_to_discord_channel(slack_channel_id):
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
        await refresh_channel_cache_file()
        return discord_channel.id

async def discord_channel_to_slack_channel(discord_channel_id):
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
        await refresh_channel_cache_file()
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
    return await webhook.send(content=message, username=username, avatar_url=avatar_url, wait=True, allowed_mentions=allowed_mentions)

async def edit_with_webhook(discord_channel_id, message_id, text, thread=""):
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
        print("No webhook found to edit!")
        return
    #print(f"Sending message to {webhook}: {message}, {username}, {avatar_url}")
    return await webhook.edit_message(message_id=message_id, content=text, allowed_mentions=allowed_mentions)



@sapp.event("reaction_added")
async def reaction_added(event, say):
    emoji = event["event"]["reaction"]
    print(emoji)

@sapp.event({"type": "message", "subtype": None}) # Slack message listening, send to discord
async def handle_message(event, say, ack):
    await ack()
    message = event
    sclient = sapp.client
    #print(message)

    #await say(":)")
    try:
        user_info = (await sclient.users_info(user=message["user"]))["user"]
        if user_info["profile"]["display_name"]:
            display_name = user_info["profile"]["display_name"]
        else:
            display_name = user_info["profile"]["real_name"]
        try:
            avatar_url = user_info["profile"]["image_original"]
        except KeyError:
            avatar_url = user_info["profile"]["image_512"]
    except BoltError as e:
        print(f"Error getting user profile info: {e}")
        display_name = "Unknown User"
        avatar_url = "https://cloud-mixfq3elm-hack-club-bot.vercel.app/0____.png"
    discord_channel = await slack_channel_to_discord_channel(message["channel"])
    if discord_channel is None:
        print("Discord channel not found")
        return

    sent_discord_message_object = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(send_with_webhook(message=message["text"], username=display_name, avatar_url=avatar_url,
                          discord_channel_id=int(discord_channel)), dbot.loop))

    await db_add_message(s_message_data=message, d_message_object=sent_discord_message_object, source="slack")


@sapp.event(event={"type": "message", "subtype": "message_deleted"}) # Slack message deletion
async def handle_slack_message_deletion(event, say, ack):
    await ack()
    message = event
    print(message)

    with sqlite3.connect("main.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, discord_message_id, discord_channel_id FROM messages WHERE slack_message_ts = ?", (message["previous_message"]["ts"],))
        record_id, discord_message_id, discord_channel_id = cur.fetchone()
        discord_message_object = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(dbot.get_channel(discord_channel_id).fetch_message(discord_message_id), loop=dbot.loop))
        try:
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(discord_message_object.delete(), loop=dbot.loop))
        except discord.errors.NotFound:
            conn.close()
            return
        cur.execute("DELETE FROM messages WHERE id = ?", (record_id,))
        conn.commit()
        conn.close()


@sapp.event(event={"type": "message", "subtype": "message_changed"}) # Slack message editing
async def handle_slack_message_edit(event, say, ack):
    await ack()
    message = event["message"]
    print(message)

    with sqlite3.connect("main.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, discord_message_id, discord_channel_id FROM messages WHERE slack_message_ts = ?", (message["ts"],))
        record_id, discord_message_id, discord_channel_id = cur.fetchone()
        discord_message_object = await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(dbot.get_channel(discord_channel_id).fetch_message(discord_message_id), loop=dbot.loop))
        try:
            #await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(discord_message_object.edit(content=message["text"]), loop=dbot.loop))
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(edit_with_webhook(discord_channel_id=discord_channel_id, message_id=discord_message_id, text=message["text"]), dbot.loop))
        except discord.errors.NotFound as e:
            print(e)
        conn.close()




@dbot.event
async def on_ready():
    global main_discord_server_object
    print('Logged on as', dbot.user)
    main_discord_server_object = dbot.get_guild(discord_server_id)
    print(await slack_channel_to_discord_channel("C07V1V34W48"))

@dbot.event
async def on_message(message): # Discord message listening, send to slack
    sclient = sapp.client
    # don't respond to ourselves
    if message.author == dbot.user:
        return
    elif message.webhook_id != None: # Don't repost messages from the webhook
        return
    elif message.channel.type in ["public_thread", "private_thread"]:
        message.reply("Sorry, threads aren't supported yet!")
        return
    elif message.guild.id == discord_server_id:
        slack_channel_id = await discord_channel_to_slack_channel(message.channel.id)
        #print(2)
        if slack_channel_id == None:
            return
        try:
            s_message = await sclient.chat_postMessage(channel=slack_channel_id, text=message.content, username=message.author.display_name, icon_url=message.author.avatar.url) # , thread_ts="1730500285.549289"
            await db_add_message(s_message_data=s_message, d_message_object=message, source="discord")
        except BoltError as e:
            print(f"Error sending message to slack: {e}")

@dbot.event
async def on_message_delete(message):
    if message.author == dbot.user:
        return
    elif message.webhook_id != None: # Don't repost messages from the webhook
        return
    with sqlite3.connect("main.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, slack_message_ts, slack_channel_id FROM messages WHERE discord_message_id = ?", (message.id,))
        record_id, slack_message_ts, slack_channel_id = cur.fetchone()
        await sapp.client.chat_delete(channel=slack_channel_id, ts=slack_message_ts)
        cur.execute("DELETE FROM messages WHERE id = ?", (record_id,))
        conn.commit()
        conn.close()

@dbot.event
async def on_message_edit(ogmessage, newmessage):
    if newmessage.author == dbot.user:
        return
    elif newmessage.webhook_id != None: # Don't repost messages from the webhook
        return
    with sqlite3.connect("main.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, slack_message_ts, slack_channel_id FROM messages WHERE discord_message_id = ?", (newmessage.id,))
        record_id, slack_message_ts, slack_channel_id = cur.fetchone()
        try:
            await sapp.client.chat_update(channel=slack_channel_id, ts=slack_message_ts, text=newmessage.content)
        except BoltError as e:
            print(f"Error sending message edit to slack: {e}")
        conn.close()


async def start_main():
    with open("slack_app_token", "r") as token_f:
        handler = AsyncSocketModeHandler(sapp, token_f.read())
    await handler.start_async()

#slack_events_adapter.start(port=3000)
#slack_thread = threading.Thread(target=SocketModeHandler.start, args=('sapp', open("slack_bot_token", "r").read()))
#asyncio.run((await AsyncSocketModeHandler(sapp, open("slack_bot_token", "r").read()).start_async()))
#slack_thread.start()

try_setup_sql_first_time()
threading.Thread(target=asyncio.run, args=(start_main(),)).start()

intents = discord.Intents.all()
intents.message_content = True
dbot.run(open("discord_token", "r").read())