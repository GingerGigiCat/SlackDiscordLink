import discord
from discord.ext import commands

#import slack_sdk
#from slackeventsapi import SlackEventAdapter
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.error import *

from slack_bolt.oauth.async_oauth_settings import AsyncOAuthSettings
from slack_sdk.oauth import AuthorizeUrlGenerator
from flask import Flask, request, make_response
from slack_sdk.web.async_client import AsyncWebClient
from slack_bolt.authorization import AuthorizeResult
from slack_sdk.oauth.installation_store import FileInstallationStore, Installation
from slack_sdk.oauth.state_store import FileOAuthStateStore


import json
import time
import os
import threading
import asyncio
import concurrent.futures
import functools
import sqlite3

from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()


person_to_complain_at_name = "Gigi Cat"
person_to_complain_at_slack_id = "U07DHR6J57U"
slack_url = "hackclub.slack.com"
with open("domain_name", "r") as f:
    domain_name = f.read()
oauth_state_store = FileOAuthStateStore(expiration_seconds=600, base_dir="./oauth_data")
installation_store = FileInstallationStore(base_dir="./oauth_data")

dbot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
discord_server_id = 1301317329333784668
main_discord_server_object = None
allowed_mentions = discord.AllowedMentions(roles=False, everyone=False)
allowed_channels = ["hackclub-discord-bridge-management", "bot-spam"] # Blank means all channel are allowed, this had to be added because of hack club things


with open("slack_bot_token", "r") as token_f:
    with open("slack_signing_secret", "r") as signing_secret_f:
        with open("slack_client_id", "r") as client_id_f:
            with open("slack_client_secret", "r") as client_secret_f:
                slack_client_id = client_id_f.read()
                slack_client_secret = client_secret_f.read()
                sapp = AsyncApp(signing_secret=signing_secret_f.read(),
                                token=token_f.read())

                flask_app = Flask(__name__)

                authorise_url_generator = AuthorizeUrlGenerator(
                    client_id=slack_client_id,
                    user_scopes=["users.profile:read"]
                )

#authorise_url_generator.generate()
@sapp.event("callback")
async def on_oauth_callback(what):
    print(what)

async def get_oauth_url(discord_user_obj: discord.User = None):
    state = oauth_state_store.issue()
    url = authorise_url_generator.generate(state)

    try:
        with sqlite3.connect("main.db") as conn:
            cur = conn.cursor()
            cur.execute("SELECT is_authorised, send_to_slack_allowed, banned FROM members WHERE discord_user_id = ?", (discord_user_obj.id,))
            is_authorised, send_to_slack_allowed, banned = cur.fetchone()
            cur.execute("""
            REPLACE INTO members(discord_user_id, discord_pfp_url, discord_display_name, discord_username, state_temp, is_authorised, send_to_slack_allowed, banned)
            values(?, ?, ?, ?, ?, ?, ? , ?)
            """, (discord_user_obj.id, discord_user_obj.avatar.url, discord_user_obj.display_name, discord_user_obj.name, state, 0, send_to_slack_allowed, banned))
            conn.commit()
    except sqlite3.OperationalError as e:
        print(e)

    return url

@flask_app.route("/slack/oauth/callback", methods=["GET"])
async def oauth_callback():
    if "code" in request.args:
        if oauth_state_store.consume(request.args["state"]):
            client = AsyncWebClient()

            oauth_response = await client.oauth_v2_access(
                client_id=slack_client_id,
                client_secret=slack_client_secret,
                #redirect_uri=f"https://{domain_name}", # I don't know this may be wrong so if there's problems then maybe blame this line
                code=request.args["code"]
            )
            installed_enterprise = oauth_response.get("enterprise") or {}
            is_enterprise_install = oauth_response.get("is_enterprise_install")
            installed_team = oauth_response.get("team") or {}
            installer = oauth_response.get("authed_user") or {}
            incoming_webhook = oauth_response.get("incoming_webhook") or {}
            bot_token = oauth_response.get("access_token")
            user_token = installer.get("access_token")
            bot_id = None
            user_id = installer.get("id")
            profile = (await sapp.client.users_profile_get(token=user_token))["profile"]
            print(profile)
            try:
                user_pfp = profile["image_original"]
            except KeyError:
                user_pfp = profile["image_512"]
            enterprise_url = None
            try:
                display_name = profile["display_name"]
            except KeyError:
                display_name = profile["real_name"]

            if bot_token is not None:
                auth_test = await client.auth_test(token=bot_token)
                bot_id = auth_test["bot_id"]
                if is_enterprise_install:
                    enterprise_url = await auth_test.get("url")
            try:
                with sqlite3.connect("main.db") as conn:
                    cur = conn.cursor()
                    cur.execute("""
                    UPDATE members
                    SET slack_token = ?,
                        state_temp = "",
                        slack_user_id = ?,
                        slack_display_name = ?,
                        slack_pfp_url = ?,
                        is_authorised = 1
                    WHERE state_temp = ?
            
                    """, (user_token, user_id, display_name, user_pfp, request.args["state"]))
            except sqlite3.OperationalError as e:
                print(f"Failed to put slack bits in the members database: {e}")
                return f"<h1> Failed to access slack user database, please DM <a href=\"https://{slack_url}/team/{person_to_complain_at_slack_id}\">@{person_to_complain_at_name}</a></h1>"
            print("woah")
            return "<h1> Yay you're authenticated!</h1>\n<h2> (You can close this tab now) </h2>"

        else:
            return "<h1> Uhhh it probably timed out so generate a new link and try again :)</h1>"


#print(get_oauth_url())


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
        slack_thread_ts TEXT,
        send_to_slack_allowed INT NOT NULL,
        send_to_discord_allowed INT NOT NULL
    )
    """

    members_table_statement = """
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        slack_user_id TEXT,
        discord_user_id INT UNIQUE,
        slack_pfp_url TEXT,
        discord_pfp_url TEXT,
        slack_display_name TEXT,
        discord_display_name TEXT,
        discord_username TEXT,
        slack_token TEXT,
        state_temp TEXT,
        is_authorised INT NOT NULL,
        send_to_slack_allowed,
        banned INT,
        constraint chk_null check (slack_user_id is not null or discord_user_id is not null)
    )
    """

    try:
        with sqlite3.connect(database_name) as conn:
            cursor = conn.cursor()
            cursor.execute(messages_table_statement) # Create the table of messages if it doesn't exist
            cursor.execute(channels_table_statement) # Create the table of channels if it doesn't exist
            cursor.execute(members_table_statement) # Create it for members

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
        slack_chan_name = await get_slack_channel_name(slack_channel_id)
        if not (allowed_channels == None or slack_chan_name in allowed_channels):
            return None
        discord_channel = await get_discord_channel_object_from_name(slack_chan_name)
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
        discord_chan_name = discord_channel.name()
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
            #print(wh)
            if wh.user.id == dbot.user.id:
                webhook = wh
                break
    if not webhook:
        print(f"Creating new webhook in #{channel.name}")
        webhook = await channel.create_webhook(name="Slack Link")
    #print(f"Sending message to {webhook}: {message}, {username}, {avatar_url}")
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

# TODO: WORKING ON THIS
async def check_user(message: discord.Message = None, discord_author_id = None): # Function to check if a user is allowed to send a message from discord to slack, given a discord message object
    try:
        discord_author_id = message.author.id
    except:
        pass
    with sqlite3.connect("main.db") as conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT slack_pfp_url, slack_display_name, slack_token, send_to_slack_allowed, banned FROM members WHERE discord_user_id = ?", (discord_author_id,))
            fetched = cur.fetchone()
            if fetched == None:
                return "notindatabase"
            slack_pfp_url, slack_display_name, slack_token, send_to_slack_allowed, banned = fetched
            if send_to_slack_allowed != 0 and banned != 1:
                token_test = await sapp.client.auth_test(token=slack_token)
                if token_test["ok"] == True:
                    return True
                else:
                    return token_test["error"]
            else:
                return "unallowed"
        except Exception as e:
            return e


async def do_the_whole_user_check(message: discord.Message):
    check_result = await check_user(message)
    if check_result != True:
        if check_result == "unallowed":
            await reply_to_author(message,
                                  "Looks like you're banned or muted, if you think this is a mistake, cont```````````````````````````````````````act the moderation team or ask in #hackclub-discord-bridge-management in slack or discord, or #purgatory in discord")
        elif check_result in ["token_revoked", "not_authed", "token_expired", "token_revoked"]:
            await reply_to_author(message,
                                  f"Hmmm you might need to authenticate yourself again, try running /auth in the discord server.\nDebug message: {check_result}")
        elif check_result == "notindatabase":
            await reply_to_author(message,
                                  "Looks like you need to authenticate with slack! Run **/auth** in the bridge discord server to get started.")
        else:
            print(check_result)
            await reply_to_author(message,
                                  f"Hmmm something went very wrong, maybe you need to reverify? Try running /auth in the discord server, and complain at [@{person_to_complain_at_name}](https://{slack_url}/team/{person_to_complain_at_slack_id}) and give them {check_result}")
        return check_result
    else:
        return True

async def reply_to_author(message: discord.Message, the_text):
    try:
        await message.author.send(the_text)
    except:
        await message.reply(the_text)


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
        if await do_the_whole_user_check(message) == True:
            pass
        else:
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
    if await do_the_whole_user_check(message) == True:
        pass
    else:
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

intents = discord.Intents.all()
intents.message_content = True
threading.Thread(target=dbot.run, args=(open("discord_token", "r").read(),)).start()
time.sleep(4)
asyncio.set_event_loop(dbot.loop)
try_setup_sql_first_time()
threading.Thread(target=asyncio.run, args=(start_main(),)).start()
threading.Thread(target=flask_app.run, kwargs={"port": 3000}).start()
#print(asyncio.run(get_oauth_url(dbot.get_user(721745855207571627)),)) # generate an oauth url for my discord user
print(asyncio.run(check_user(discord_author_id=721745855207571627)))



scheduler.start() # DO NOT REMOVE THIS IT BREAKS EVERYTHING PYTHON IS WEIRD

