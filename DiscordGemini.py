import discord
from discord.ext import commands
import json
import os
from google import genai
from google.genai.errors import ClientError
from dotenv import load_dotenv

# =========================
# CONFIG
# =========================
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("API_KEY")
MEMORY_FILE = os.getenv("MEMORY_FILE") or "Memories.json"

SHORT_TERM_TURNS = 6

MODELS = [
    "gemma-3-27b-it",
    "gemma-3-12b-it",
    "gemma-3-4b-it",
    "gemma-3-2b-it",
    "gemma-3-1b-it",
    "gemini-2.5-flash-lite",
]

# =========================
# INIT
# =========================
bot = discord.Bot()
client_ai = genai.Client(api_key=API_KEY)

# user_id -> {"short": [], "long": []}
user_sessions = {}
persistent_memories = {}

# =========================
# MEMORY FILE
# =========================
def load_memories():
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except:
        return {}

def save_memories(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

persistent_memories = load_memories()

# =========================
# MODEL CALL WITH FALLBACK
# =========================
def call_model(prompt):
    for model in MODELS:
        try:
            chat = client_ai.chats.create(model=model)
            r = chat.send_message(prompt)
            return r.candidates[0].content.parts[0].text.strip()
        except ClientError as e:
            if e.status_code == 429:  # quota exceeded
                continue
            raise e
    return "I'm temporarily unavailable."

# =========================
# LONG-TERM MEMORY UPDATE
# =========================
def update_memories(user_message, existing_memories):
    prompt = f"""
You are a LONG-TERM MEMORY FILTER.

Existing memories:
{chr(10).join('- ' + m for m in existing_memories) or 'NONE'}

New user message:
{user_message}

STRICT RULES:
- Save only durable personal info (identity, preferences, projects, constraints)
- Ignore conversation, questions, debugging, temporary info
- If nothing qualifies, respond EXACTLY: NONE
- Merge and deduplicate
- Keep each memory factual, neutral, under 80 characters
- Do not reference the conversation or user message
- Keep the amount of memories manageable (max 20)
- If the user has more than 15 memories, prioritize the most relevant ones
- Delete less relevant memories if necessary
- If the message has 'Always must be included' ensure that memory is kept and is not edited in any way.
- Output bullet list only:
EXAMPLE OUTPUT:
- Memory 1
- Memory 2
"""

    result = call_model(prompt)
    if result.strip().upper() == "NONE":
        print(" No new memories to add.")
        return existing_memories  # keep old memories if nothing new

    # Parse bullets
    new_memories = [line[2:].strip() for line in result.splitlines() if line.startswith("- ")]
    # Merge with existing memories, deduplicate

    return new_memories

# =========================
# RELEVANT MEMORY FILTER
# =========================
def get_relevant_memories(user_message, long_term):
    if not long_term:
        return []

    prompt = f"""
You are a memory relevance filter.
User said: "{user_message}"

Existing memories:
{chr(10).join('- ' + m for m in long_term)}

RULES:
- Only keep memories that are directly relevant to the user's message.
- Discard unrelated memories.
- Output a bullet list of relevant memories only, or NONE if none apply.
- The name is ALWAYS relevant and should almost ALWAYS be included.
- Do not modify the memories in any way.
- If the memory includes 'Always must be included' the memory must be included in the output.
- EXAMPLE OUTPUT:
- Relevant memory 1
- Relevant memory 2
"""
    if long_term == []:
        return []
    result = call_model(prompt)
    if result.strip().upper() == "NONE":
        print(" No relevant memories found.")
        return []
    
    return [line[2:].strip() for line in result.splitlines() if line.startswith("- ")]

# =========================
# PROMPT BUILD
# =========================
def build_prompt(long_term, short_term):
    prompt = (
        "System: You are a helpful Discord assistant. "
        "Use the user's name when appropriate. "
        "Do not reference personal memories unless the user explicitly mentions them. "
        "If you do use personal details, do so sparingly and only when directly relevant. "
        "All of your messages should be formatted according to Discord markdown standards. "
        "Your response can be a MAXIMUM of 2000 characters, any longer and it will be cut off!"
        "Focus on providing clear, helpful, and neutral responses.\n\n"
    )

    # Filter memories relevant to last message
    if long_term and short_term:
        relevant = get_relevant_memories(short_term[-1]['content'], long_term)
        if relevant:
            prompt += "Relevant user memories:\n"
            for m in relevant:
                prompt += f"- {m}\n"
            prompt += "\n"

    prompt += "Recent conversation:\n"
    for msg in short_term:
        role = "You" if msg['role'] == "user" else "Bot"
        prompt += f"{role}: {msg['content']}\n"

    return prompt

def trim_short_term(short_term):
    return short_term[-SHORT_TERM_TURNS * 2:]

# =========================
# SLASH COMMAND
# =========================
@bot.slash_command(name="ask", description="Ask the bot a question")
async def ask(ctx: discord.ApplicationContext, message: str):
    # Immediately defer to buy time for long AI calls
    await ctx.defer(ephemeral=False)  # ephemeral=False makes message visible to everyone in the channel

    user_id = str(ctx.user.id)

    # Initialize sessions if needed
    if user_id not in user_sessions:
        user_sessions[user_id] = {"short": []}
    if user_id not in persistent_memories:
        persistent_memories[user_id] = {"long": []}

    short = user_sessions[user_id]["short"]
    long = persistent_memories[user_id]["long"]

    # Short-term memory
    short.append({"role": "user", "content": message})
    short = trim_short_term(short)
    user_sessions[user_id]["short"] = short

    # Update long-term memory
    persistent_memories[user_id]["long"] = update_memories(message, long)
    save_memories(persistent_memories)

    # Build prompt & get reply (wrap in a thread to avoid blocking)
    import asyncio
    prompt = build_prompt(persistent_memories[user_id]["long"], short)
    reply = await asyncio.to_thread(call_model, prompt)

    # Trim for Discord 2000-char limit
    if len(reply) > 2000:
        reply = reply[:1997] + "..."

    # Append assistant reply to short-term memory
    short.append({"role": "assistant", "content": reply})
    short = trim_short_term(short)
    user_sessions[user_id]["short"] = short

    # Send reply via followup
    await ctx.followup.send(reply)

# =========================
# BOT READY EVENT
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} — Ready!")

# =========================
# RUN BOT
# =========================
bot.run(DISCORD_TOKEN)
