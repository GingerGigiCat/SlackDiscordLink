import os

import discord
from discord.ext import commands
import slack_sdk
from slackeventsapi import SlackEventAdapter

SLACK_SIGNING_SECRET = open("slack_token", "r").read()

slack_events_adapter = SlackEventAdapter(SLACK_SIGNING_SECRET, endpoint="/slack/events")
@slack_events_adapter.on(