import os
import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import aiohttp
import PyPDF2
import io
from collections import defaultdict

import discord
from discord.ext import commands
from dotenv import load_dotenv
import google.generativeai as genai


from client import supabase

class StudySession:
    def __init__(self, user_id: int, guild_id: int, topic: str, bullet_points: List[str], target_cycles: int):
        self.user_id = user_id
        self.guild_id = guild_id
        self.topic = topic
        self.bullet_points = bullet_points
        self.start_time = datetime.utcnow()
        self.current_cycle = 0
        self.target_cycles = target_cycles
        self.quiz_scores = []
        self.is_active = True
        self.timer_task = None
        self.work_time = 25 * 60  # 25 minutes in seconds
        self.break_time = 5 * 60  # 5 minutes in seconds
        self.long_break_time = 15 * 60  # 15 minutes for long break after 4 cycles
        self.in_break = False


class StudyBuddy(commands.Bot):

    ## study command
    @commands.command(name='study')
    @commands.cooldown(1, 300, commands.BucketType.user) 


    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.active_sessions: Dict[int, StudySession] = {}  # key: channel_id
        self.rate_limits: Dict[int, datetime] = {}
        self.server_configs: Dict[int, Dict[str, Any]] = {}

    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name="🍅 !! Study Sessions !!")
        )

    async def on_voice_state_update(self, member, before, after):
        ## for handling vc changes of user

        user_id = member.id

        if user_id in self.active_sessions:
            session = self.active_sessions[user_id]
            study_channel = await self.get_study_channel(member.guild)

            if study_channel and (not after.channel or after.channel.id != study_channel.id):
                await self.cancel_study_session(user_id, member.guild.io)

    async def load_server_config(self, guild_id: int):
        try:
            response = supabase.table('server_configs').select('*').eq('guild_id', str(guild_id)).execute()

            if response.data:
                config = response.data[0] ## was found
                return {
                    'study_channel_id': int(config['study_channel_id']) if config['study_channel_id'] != '0' else None,
                    'study_channel_name': config['study_channel_name'],
                    'prefix': config['prefix'],
                    'max_session_duration': config['max_session_duration']
                }
            else:
                default_config = {
                    'study_channel_id': None,
                    'study_channel_name': 'study-vc',
                    'prefix': '!',
                    'max_session_duration': 120
                }
                await self.save_server_config(guild_id, default_config)
                return default_config
        except Exception as e:
            print(f"Error loading server config: {e}")

            return {
                'study_channel_id': None,
                'study_channel_name': 'study-vc',
                'prefix': '!',
                'max_session_duration': 120
            }
    
    async def save_server_config(self, guild_id: int, config: Dict[str, Any]):
        try:
            data = {
                'guild_id': str(guild_id),
                'study_channel_id': str(config.get('study_channel_id', '0')),
                'study_channel_name': config.get('study_channel_name', 'study-dungeon'),
                'prefix': config.get('prefix', '!'),
                'max_session_duration': config.get('max_session_duration', 120),
                'updated_at': datetime.utcnow().isoformat()
            }

            ## update
            response = supabase.table('server_configs').update(data).eq('guild_id', str(guild_id)).execute()

            if not response.data:
                ## new
                data['created_at'] = datetime.utcnow().isoformat()
                supabase.table('server_configs').insert(data).execute()

        except Exception as e:
            print(f"Error saving server config: {e}")

    

    ## functions for bot core actions

    ## flow, check vc -> move -> message contents either a prompt or file, checks first 
    ## -> create pointers with gemini api -> start pomodoro timer -> end current timer -> quiz based on pointers
    ## -> cycle -> end session 

    ## no way to check rate limiter first

    async def get_study_channel(self, guild) -> discord.VoiceChannel:
        guild_id = guild.id

        ## check first

        if guild_id not in self.server_configs:
            self.server_configs[guild_id] = await self.load_server_config(guild_id)

        config = self.server_configs[guild_id]

        if config['study_channel_id']:
            channel = guild.get_channel(config['study_channel_id'])
            if channel and isinstance(channel, discord.VoiceChannel):
                return channel

        channel = discord.utils.get(guild.voice_channels, name=config['study_channel_name'])
        return channel

    async def extract_text_from_file(self, attachment) -> str:
        ## extract text 

        text = ""

        if attachment.filename.endswith('.txt') or attachment.filename.endswith('.md'):
            content = await attachment.read():
            text = content.decode('utf-8')
        elif attachment.filename.endswith('.pdf'):
            content = await attachment.read()
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(content))
            for page in pdf_reader.pages:
                text += page.extract_text()

        return text

    async def analyze_content_with_gemini(self, content: str) -> List[str]:
        prompt = f"""
            You are an expert academic tutor and summarization assistant. Your primary goal is to help a student efficiently prepare for a study session or an exam by extracting the most critical information from their learning material.

            **Task:** Analyze the following text and generate a list of the 5 to 7 most important key concepts, definitions, and takeaways.

            **Criteria for the bullet points:**
            - **Criticality:** Each point must be essential for understanding the core topic.
            - **Clarity:** Use clear and straightforward language. Avoid jargon unless it's a defined key term.
            - **Conciseness:** Each point should be a single, complete thought, ideally no longer than one sentence.

            **Source Text:**
            ---
            {content}
            ---

            **Instructions for Output Format:**
            - Your response must contain ONLY the bullet points.
            - Do not include any introductory phrases like "Here are the key points:" or any concluding remarks.
            - Each bullet point must begin with a hyphen and a space (`- `).
            """
        try:
            response = model.generate_content(prompt)
            ## isolate
            bullet_points = [line.strip().lstrip('- ') for line in response.text.split('\n') if line.strip().startswith('-')]
            return bullet_points
        except Exception as e:
            print(f"Error with Gemini API: {e}")
            return ["StudyBuddy was unable to analyze content. Please try again with a different format."]

    async def generate_quiz_with_gemini(self, bullet_points: List[str]) -> List[Dict[str, Any]]:
        points_text = "\n".join([f"- {point}" for point in bullet_points])

        prompt = f"""
        You are an AI Quiz Designer. Your task is to create a short, effective quiz to help a student reinforce their learning after a study session.

        **Goal:** Based on the provided key points, generate a 3-question multiple-choice quiz.

        **Quiz Design Principles:**
        - **Relevance:** Each question must directly test one of the key points provided.
        - **Clarity:** Questions should be unambiguous and easy to understand.
        - **Plausible Distractors:** The incorrect options should be plausible and related to the topic to ensure the quiz is a meaningful test of knowledge, not just an obvious giveaway.

        **Source Key Points:**
        ---
        {points_text}
        ---

        **Instructions for Output Format:**
        Your entire response MUST be a single, valid JSON array. Do not include any text, explanations, or markdown formatting outside of the JSON structure.

        The JSON must follow this exact schema:
        [
            {{
                "question": "The text of the first question?",
                "options": {{
                    "A": "Option A text.",
                    "B": "Option B text.",
                    "C": "Option C text.",
                    "D": "Option D text."
                }},
                "correct_answer": "C"
            }},
            ... (two more question objects)
        ]
        """


        try:
            response = model.generate_content(prompt)
            json_start = response.text.find('[')
            json_end = response.text.rfind(']') + 1
            json_text = response.text[json_start:json_end]

            quiz_data = json.loads(json_text)
            return quiz_data
        except Exception as e:
            print(f"Quiz generation error: {e}")

            return [{
                "question": "What is the main topic being studied?",
                "options": {"A": "Mathematics", "B": "Science", "C": "Literature", "D": "History"},
                "correct_answer": "A"
            }]
        
    async def start_study_session(self, context, cycles: int, *, topic_text: str = None):
    
        user_id = context.author.id
        guild_id = context.guild.id
        study_channel = None
        content = topic_text or ""

        ## preliminary checks
        if cycles < 1 or cycles > 8:
            await context.send("❌ Number of cycles must be between 1 and 8!")
            return

        if user_id in self.active_sessions:
            await context.send("You already have an active study session! Use `!study stop` to end it.")
            return

        study_channel = await self.get_study_channel(context.guild)
        if not study_channel:
            guild_config = self.server_configs.get(context.guild.id, {})
            channel_name = guild_config.get('study_channel_name', 'study-dungeon')
            await context.send(f"❌ Study voice channel not configured! Use `!setup_study <channel>` or create a channel named '{channel_name}'.")
            return

        if context.message.attachments:
            await context.send ("📥 Processing your attachment...")
            for attachment in context.message.attachments:
                file_text = await self.extract_text_from_file(attachment)
                content += "\n\n" + file_text

        if not content.strip():
            await context.send("❌ Please provide study material either as text or file attachments!")
            return
        

        ## analyze content 
        await context.send("🧠 Analyzing your study material")
        bullet_points = await self.analyze_content_with_ai(content)

        ## create session
        session = StudySession(user_id, guild_id, topic_text or "Study Session", bullet_points, cycles)
        self.active_sessions[user_id] = session
       
        total_work_time = cycles * 25
        total_break_time = max(0, cycles - 1) * 5

        ## long break
        if cycles >= 4:
            long_breaks = (cycles - 1) // 4
            total_break_time += long_breaks * 10

        total_estimated = total_work_time + total_break_time

        embed = discord.Embed(
            title="📚 Study Session Started!",
            description=f"**Topic:** {session.topic}",
            color=0x00ff00
        )

        bullet_text = "\n".join([f"• {point}" for point in bullet_points])
        embed.add_field(name="Key Study Points", value=bullet_text, inline=False)


        progress_bar = "🔴" + "⚪" * (cycles - 1)
        embed.add_field(
            name="📊 Planned Cycles", 
            value=f"{progress_bar}\n**{cycles} cycles** planned ({total_work_time} min work + {total_break_time} min breaks = ~{total_estimated} min total)", 
            inline=False
        )

        embed.add_field(name="⏱️ Current", value="Starting Cycle 1/{}...".format(cycles), inline=False)

        await context.send(embed=embed)

        if context.author.voice
            await context.author.move_to(study_channel)
        else:
            await context.send("⚠️ Join the study voice channel to begin!")
            return
        

        ## start timer 
        session.timer_task = asyncio.create_task(self.run_pomodoro_cycle(context, session))

    async def run_pomodoro_cycle(self, context, session: StudySession):
        try:
            while session.is_active and session.current_cycle < session.target_cycles:
                session.in_break = False
                session.current_cycle += 1

                await self.send_progress_update(context, session, "work_start")

                await asyncio.sleep(session.work_time)

                if not session.is_active:
                    break

                study_channel = await self.get_study_channel(context.guild)
                if study_channel and context.author.voice and context.author.voice.channel == study_channel:
                    await ctx.send(f"⏰ {ctx.author.mention} Cycle {session.current_cycle}/{session.target_cycles} work session complete! Time for a quick quiz!")

                    quiz_score = await self.run_quiz(context, session)
                    session.quiz_scores.append(quiz_score)

                    if session.current_cycle >= session.target_cycles:
                        await self.complete_study_session(context, session)
                        break

                    ## break time
                    session.in_break = True

                    ## long or short?
                    is_long_break = session.current_cycle % 4 == 0 and session.current_cycle < session.target_cycles
                    break_duration = session.long_break_time if is_long_break else session.break_time
                    break_type = "long break" if is_long_break else "short break"
                    break_minutes = break_duration // 60

                    await context.send(f"☕ {break_type.title()} time! Relax for {break_minutes} minutes. Cycle {session.current_cycle}/{session.target_cycles} complete!")
                    await self.send_progress_update(context, session, "break_start")

                    await asyncio.sleep(break_duration)

                    if session.is_active and session.current_cycle < session.target_cycles:
                        await context.send(f"🔔 Break's over! Get ready for Cycle {session.current_cycle + 1}/{session.target_cycles} work session.")
                else:
                    break
        except asyncio.CancelledError:
            pass               
        
## loading env variables
# load_dotenv()

## config
# BOT_TOKEN = os.getenv("BOT_TOKEN")
# SUPABASE_URL = os.getenv("SUPABASE_URL")
# SUPABASE_KEY = os.getenv("SUPABASE_KEY")
# GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
#     raise ValueError("Missing required environment variables")
# supabase_client = supabase.create_client(url, key)

# ## bot setup
# intents = discord.Intents.default()
# intents.message_content = True
# intents.voice_states = True # to check only if in vc
# seen_users = set() ## cache for users seen

# # managing a state
# pomodoro_timers = {}

# client = discord.Client(intents=intents)
# ## bot actions
# @client.event
# async def on_ready():
#     print(f'We have logged in as {client.user}')

#     await client.change_presence(
#         status=discord.Status.online,
#         activity=discord.Game(name="Pomodo 🍅")
#     )

# @client.event
# async def on_message(message):
#         if message.author == client.user:
#             return

#         if message.content.startswith('!pomodoro'):
            
#             # create diff commands, split the message
#             command_parts = message.content.split()
#             command = command_parts[1] if len(command_parts) > 1 else 'help'
#             channel_id = message.channel.id

#             if(command == 'start'):
#                 if channel_id in pomodoro_timers and pomodoro_timers[channel_id]['is_running']:
#                     await message.channel.send("A Pomodoro timer is already running in this channel.")
#                     return
                
#                 try:
#                     work_minutes = 24
#                     break_minutes = 5

#                     pomodoro_timers[channel_id] = {
#                         'is_running': True,
#                         'work_time': work_minutes * 60,  
#                         'break_time': break_minutes * 60, 
#                         'user': message.author
#                     }

#                     await message.channel.send(f"Pomodoro timer started by {message.author.mention}! Starting a {work_minutes}-minute work session.")

#                     while pomodoro_timers.get(channel_id, {}).get('is_running'):
#                         try:
#                             await asyncio.sleep(pomodoro_timers[channel_id]['work_time'])
#                             if not pomodoro_timers.get(channel_id, {}).get('is_running'):
#                                 break

#                             await message.channel.send(f"Time for a {break_minutes}-minute break, {pomodoro_timers[channel_id]['user'].mention}!")

#                             await asyncio.sleep(pomodoro_timers[channel_id]['break_time'])
#                             if not pomodoro_timers.get(channel_id, {}).get('is_running'):
#                                 break
#                             await message.channel.send(f"Break's over! Time for another {work_minutes}-minute work session, {pomodoro_timers[channel_id]['user'].mention}!")              
#                         except KeyError:
#                             pass
                
#                 except Exception as e:
#                     await message.channel.send(f"An error occurred: {str(e)}")


#             elif command == 'stop':
#                 if channel_id in pomodoro_timers and pomodoro_timers[channel_id]['is_running']:
#                     pomodoro_timers[channel_id]['is_running'] = False
#                     await message.channel.send("Pomodoro timer stopped.")
#                 else:
#                     await message.channel.send("No Pomodoro timer is currently running in this channel.")

#             elif command == 'help':
#                 help_message = """
#                     placeholder cause idk what to put here yet
#                     just know that start and stop work
#                 """
                            
                
            

            

#         # if message.content.startswith('!study'):
#         #     guild = message.guild
#         #     voice_channel = discord.utils.get(guild.voice_channels, name="study-dungeon")

#         #     if voice_channel is None:
#         #         await message.channel.send("You need to be in a voice channel to use this command.")
#         #         return

#         #     if message.author.voice:
#         #         await message.author.move_to(voice_channel)
#         #         await message.channel.send(f"Moved {message.author.name} to {voice_channel.name}.")

    





# client.run(TOKEN)


