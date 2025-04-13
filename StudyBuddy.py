
import os
from dotenv import load_dotenv

import discord

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if TOKEN is None:
    raise ValueError("No token provided. Please set the BOT_TOKEN environment variable.")
    
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
        if message.author == client.user:
            return

        if message.content.startswith('!study'):
            await message.channel.send('Let\'s study together!')

client.run(TOKEN)


