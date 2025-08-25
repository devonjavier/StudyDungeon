
import os
from dotenv import load_dotenv

import discord

from client import supabase

## loading env variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if TOKEN is None:
    raise ValueError("No token provided. Please set the BOT_TOKEN environment variable.")

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
if url is None or key is None:
    raise ValueError("No Supabase credentials provided. Please set the SUPABASE_URL and SUPABASE_KEY environment variables.")

supabase_client = supabase.create_client(url, key)

## building client
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True # to check only if in vc
seen_users = set() ## cache for users seen

# managing a state
pomodoro_timers = {}

client = discord.Client(intents=intents)
## bot actions
@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
        if message.author == client.user:
            return

        if message.content.startswith('!pomodoro'):
            
            # create diff commands, split the message
            command_parts = message.content.split()
            command = command_parts[1] if len(command_parts) > 1 else 'help'
            channel_id = message.channel.id

            if(command == 'start'):
                if channel_id in pomodoro_timers and pomodoro_timers[channel_id]['is_running']:
                    await message.channel.send("A Pomodoro timer is already running in this channel.")
                    return
                
                try:
                    work_minutes = 24
                    break_minutes = 5

                    pomodoro_timers[channel_id] = {
                        'is_running': True,
                        'work_time': work_minutes * 60,  
                        'break_time': break_minutes * 60, 
                        'user': message.author
                    }

                    await message.channel.send(f"Pomodoro timer started by {message.author.mention}! 
                    Starting a {work_minutes}-minute work session.")

                    while pomodoro_timers.get(channel_id, {}).get('is_running'):
                        try:
                            await asyncio.sleep(pomodoro_timers[channel_id]['work_time'])
                            if not pomodoro_timers.get(channel_id, {}).get('is_running'):
                                break

                            await message.channel.send(f"Time for a {break_minutes}-minute break, {pomodoro_timers[channel_id]['user'].mention}!")

                            await asyncio.sleep(pomodoro_timers[channel_id]['break_time'])
                            if not pomodoro_timers.get(channel_id, {}).get('is_running'):
                                break
                            await message.channel.send(f"Break's over! Time for another {work_minutes}-minute work session, {pomodoro_timers[channel_id]['user'].mention}!")
                        
                        except KeyError:
                            break

            elif command == 'stop':
                if channel_id in pomodoro_timers and pomodoro_timers[channel_id]['is_running']:
                    pomodoro_timers[channel_id]['is_running'] = False
                    await message.channel.send("Pomodoro timer stopped.")
                else:
                    await message.channel.send("No Pomodoro timer is currently running in this channel.")

            elif command == 'help':
                help_message = """
                    placeholder cause idk what to put here yet
                    just know that start and stop work
                """
                            
                
            

            

        # if message.content.startswith('!study'):
        #     guild = message.guild
        #     voice_channel = discord.utils.get(guild.voice_channels, name="study-dungeon")

        #     if voice_channel is None:
        #         await message.channel.send("You need to be in a voice channel to use this command.")
        #         return

        #     if message.author.voice:
        #         await message.author.move_to(voice_channel)
        #         await message.channel.send(f"Moved {message.author.name} to {voice_channel.name}.")

    





client.run(TOKEN)


