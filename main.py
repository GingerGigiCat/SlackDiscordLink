import os
import discord
from discord.ext import commands
import slack_sdk
from slackeventsapi import SlackEventAdapter
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import threading

dbot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

sclient = WebClient(token=open("slack_token", "r").read())

SLACK_SIGNING_SECRET = open("slack_signing_secret", "r").read()
slack_events_adapter = SlackEventAdapter(SLACK_SIGNING_SECRET, endpoint="/slack/events")

dtos = {} # USE THIS MAINLY, the other one is just a copy of this but reversed
stod = {v: k for k, v in dtos.items()} # Swap the discord to slack channel dictionary around so that a discord channel can be looked up from the slack channel

def get_slack_channel_name(channel_id):
    try:
        response = sclient.conversations_info(channel=channel_id)
        channel_name = response['channel']['name']
        return channel_name
    except SlackApiError as e:
        print(f"Error fetching channel info: {e.response['error']}")
        return None

@slack_events_adapter.on("reaction_added")
def reaction_added(event_data):
    emoji = event_data["event"]["reaction"]
    print(emoji)

@slack_events_adapter.on("message")
def handle_message(event_data):
    message = event_data["event"]
    # If the incoming message contains "hi", then respond with a "Hello" message
    if message.get("subtype") is None and "hi458" in message.get('text'):
        channel = message["channel"]
        print(channel)
        message = "Hello <@%s>! :tada:" % message["user"]
        sclient.chat_postMessage(channel=channel, text=message)


@dbot.event
async def on_ready():
    print('Logged on as', dbot.user)

@dbot.event
async def on_message(message):
    # don't respond to ourselves
    if message.author == dbot.user:
        return

    sclient.chat_postMessage(channel="#bot-spam", text=message.content, username=message.author.display_name, icon_url=message.author.avatar.url)

#slack_events_adapter.start(port=3000)
slack_thread = threading.Thread(target=slack_events_adapter.start, kwargs={'port': 3000})
slack_thread.start()

intents = discord.Intents.all()
intents.message_content = True
dbot.run(open("discord_token", "r").read())