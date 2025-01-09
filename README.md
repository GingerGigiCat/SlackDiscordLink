# Chat between Slack and Discord

## If you're in hack club and looking for a live demo, either join [https://discord.gg/bm5VDG3bc4](https://discord.gg/bm5VDG3bc4) and [#hackclub-discord-bridge-management](https://hackclub.slack.com/archives/C07V1V34W48), or press the demo button in high seas for a video.


**Have you ever felt disappointed or confused by having to use slack? <p></p> Annoyed by another app open using up your RAM and your precious screen real estate? <p></p>**

Well suffer no longer.

It was previously able to access any channel, but I had to restrict it due to issues with moderating it. It does have full authentication though now, so I will try again.

Therefore, at the moment it can **only access [#hackclub-discord-bridge-management](https://hackclub.slack.com/archives/C07V1V34W48) and #bot-spam**

## Features

- **Sends** messages from slack to discord and vice versa
- Detects which **channel** messages are sent in and sends them to the corresponding channel in the other platform of the same name
- **Converts emojis** including both custom and standard from slack to discord
- **Copies custom emojis** from slack to discord, and tracks which ones are used most often so prioritises them, since discord has a limited number of emojis
- Relays **reactions**, and reacts on your behalf on slack when you react to a discord message
- Transfers messages in **threads**, you can create threads in discord or slack, it doesn't matter


### Disclaimer:
GitHub Copilot helped a little with the css of the internal web server for authentication as I am terrible at css

The Markdown conversion, md.py, was mostly written and contributed by [@Neon](https://hackclub.slack.com/team/U07L45W79E1), although I fixed it and added link conversion from discord to slack, as well as made it integrate with the rest of the code.