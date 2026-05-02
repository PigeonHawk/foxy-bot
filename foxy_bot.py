import discord
import random
import aiohttp
import os
import asyncio
from collections import deque

# --- CONFIG ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
JUMPSCARE_CHANCE = 0.067  # 6.7% chance per message

GITHUB_API_URL_GIFS = "https://api.github.com/repos/PigeonHawk/foxy-bot/contents/gifs"
GITHUB_API_URL_MUSIC = "https://api.github.com/repos/PigeonHawk/foxy-bot/contents/music"
GITHUB_RAW_MUSIC = "https://raw.githubusercontent.com/PigeonHawk/foxy-bot/main/music/"

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

gif_urls = []         # Cached list of GIF URLs
music_files = []      # Cached list of music filenames
song_queue = deque()  # Queue of songs to play
is_looping = False    # Whether Gold Saucer loop mode is active
gold_saucer_songs = []  # Songs used in the Gold Saucer loop


# ─────────────────────────────────────────────
#  GITHUB FETCHERS
# ─────────────────────────────────────────────

async def fetch_gifs_from_github():
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_API_URL_GIFS) as response:
            if response.status == 200:
                files = await response.json()
                urls = [
                    f["download_url"]
                    for f in files
                    if f["name"].lower().endswith(".gif")
                ]
                print(f"✅ Loaded {len(urls)} GIFs from GitHub!")
                return urls
            else:
                print(f"❌ Failed to fetch GIFs: HTTP {response.status}")
                return []


async def fetch_music_from_github():
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_API_URL_MUSIC) as response:
            if response.status == 200:
                files = await response.json()
                names = [
                    f["name"]
                    for f in files
                    if f["name"].lower().endswith(".mp3")
                ]
                print(f"✅ Loaded {len(names)} songs from GitHub!")
                return names
            else:
                print(f"❌ Failed to fetch music: HTTP {response.status}")
                return []


# ─────────────────────────────────────────────
#  MUSIC PLAYER
# ─────────────────────────────────────────────

async def play_next(voice_client, channel):
    """Play the next song in the queue."""
    global is_looping, gold_saucer_songs

    if not song_queue:
        # If looping is on, refill the queue with Gold Saucer songs
        if is_looping and gold_saucer_songs:
            random.shuffle(gold_saucer_songs)
            song_queue.extend(gold_saucer_songs)
        else:
            await channel.send("✅ Queue is empty, all songs have been played!")
            return

    song_name = song_queue.popleft()
    song_url = GITHUB_RAW_MUSIC + song_name.replace(" ", "%20")

    ffmpeg_options = {
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        "options": "-vn"
    }

    source = discord.FFmpegPCMAudio(song_url, **ffmpeg_options)
    display_name = song_name.replace(".mp3", "")

    def after_playing(error):
        if error:
            print(f"Player error: {error}")
        asyncio.run_coroutine_threadsafe(play_next(voice_client, channel), client.loop)

    voice_client.play(source, after=after_playing)
    await channel.send(f"🎵 Now playing: **{display_name}**")


# ─────────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────────

@client.event
async def on_ready():
    global gif_urls, music_files
    print(f"🦊 Foxy Bot is online as {client.user}!")
    gif_urls = await fetch_gifs_from_github()
    music_files = await fetch_music_from_github()


@client.event
async def on_message(message):
    global gif_urls, music_files, is_looping, gold_saucer_songs

    # Ignore the bot's own messages
    if message.author == client.user:
        return

    content = message.content.strip().lower()

    # ── !reloadgifs ──────────────────────────
    if content == "!reloadgifs":
        await message.channel.send("🔄 Reloading GIFs from GitHub...")
        gif_urls = await fetch_gifs_from_github()
        await message.channel.send(f"✅ Done! Loaded **{len(gif_urls)}** GIFs.")
        return

    # ── !reloadmusic ─────────────────────────
    if content == "!reloadmusic":
        await message.channel.send("🔄 Reloading music from GitHub...")
        music_files = await fetch_music_from_github()
        await message.channel.send(f"✅ Done! Loaded **{len(music_files)}** songs.")
        return

    # ── !songs ───────────────────────────────
    if content == "!songs":
        if not music_files:
            await message.channel.send("❌ No songs found! Try `!reloadmusic` first.")
            return
        song_list = "\n".join([f"🎵 {s.replace('.mp3', '')}" for s in music_files])
        await message.channel.send(f"**Available songs:**\n{song_list}")
        return

    # ── !join ────────────────────────────────
    if content == "!join":
        if message.author.voice:
            channel = message.author.voice.channel
            await channel.connect()
            await message.channel.send(f"🦊 Joined **{channel.name}**!")
        else:
            await message.channel.send("❌ You need to be in a voice channel first!")
        return

    # ── !leave ───────────────────────────────
    if content == "!leave":
        if message.guild.voice_client:
            is_looping = False
            gold_saucer_songs = []
            song_queue.clear()
            await message.guild.voice_client.disconnect()
            await message.channel.send("👋 Left the voice channel and cleared the queue.")
        else:
            await message.channel.send("❌ I'm not in a voice channel!")
        return

    # ── !goldsaucer ──────────────────────────
    if content == "!goldsaucer":
        if not message.author.voice:
            await message.channel.send("❌ You need to be in a voice channel first!")
            return

        if not music_files:
            await message.channel.send("❌ No songs loaded! Try `!reloadmusic` first.")
            return

        # Find all songs with "saucer" in the name
        saucer_songs = [s for s in music_files if "saucer" in s.lower()]

        if not saucer_songs:
            await message.channel.send("❌ No songs with 'Saucer' in the name found in the music folder!")
            return

        # Join voice channel if not already in one
        voice_client = message.guild.voice_client
        if not voice_client:
            channel = message.author.voice.channel
            voice_client = await channel.connect()
            await message.channel.send(f"🦊 Joined **{channel.name}**!")
        elif voice_client.is_playing():
            voice_client.stop()

        # Set up loop
        is_looping = True
        gold_saucer_songs = saucer_songs.copy()
        song_queue.clear()
        random.shuffle(gold_saucer_songs)
        song_queue.extend(gold_saucer_songs)

        song_names = "\n".join([f"🎵 {s.replace('.mp3', '')}" for s in saucer_songs])
        await message.channel.send(f"🎰 **Welcome to the Gold Saucer!** 🎰\nLooping these songs forever:\n{song_names}\n\nType `!stoploop` to stop looping or `!leave` to disconnect.")
        await play_next(voice_client, message.channel)
        return

    # ── !stoploop ────────────────────────────
    if content == "!stoploop":
        if is_looping:
            is_looping = False
            gold_saucer_songs = []
            await message.channel.send("🔁 Loop stopped! The current queue will finish and then stop.")
        else:
            await message.channel.send("❌ No loop is currently active.")
        return

    # ── !play (random or specific) ───────────
    if content.startswith("!play"):
        voice_client = message.guild.voice_client

        if not voice_client:
            await message.channel.send("❌ I'm not in a voice channel! Use `!join` first.")
            return

        if not music_files:
            await message.channel.send("❌ No songs loaded! Try `!reloadmusic`.")
            return

        args = message.content.strip()[5:].strip()  # Everything after !play

        if args == "":
            # Random song
            song = random.choice(music_files)
        else:
            # Specific song search (partial match)
            matches = [s for s in music_files if args.lower() in s.lower().replace(".mp3", "")]
            if not matches:
                await message.channel.send(f"❌ No song found matching **{args}**. Use `!songs` to see available songs.")
                return
            song = matches[0]

        song_queue.append(song)
        display_name = song.replace(".mp3", "")

        if not voice_client.is_playing():
            await play_next(voice_client, message.channel)
        else:
            await message.channel.send(f"➕ Added to queue: **{display_name}**")
        return

    # ── !queue ───────────────────────────────
    if content == "!queue":
        if not song_queue:
            await message.channel.send("📭 The queue is empty!")
        else:
            queue_list = "\n".join([f"{i+1}. {s.replace('.mp3', '')}" for i, s in enumerate(song_queue)])
            loop_status = " 🔁 (looping)" if is_looping else ""
            await message.channel.send(f"**Current queue{loop_status}:**\n{queue_list}")
        return

    # ── !skip ────────────────────────────────
    if content == "!skip":
        voice_client = message.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await message.channel.send("⏭️ Skipped!")
        else:
            await message.channel.send("❌ Nothing is playing right now!")
        return

    # ── Jumpscare (10% chance on any message) ─
    if random.randint(1, 100) == 1:
        gif_urls = await fetch_gifs_from_github()

    if gif_urls and random.random() < JUMPSCARE_CHANCE:
        gif = random.choice(gif_urls)
        await message.reply(gif)


client.run(BOT_TOKEN)
@client.event
async def on_ready():
    global gif_urls
    print(f"🦊 Foxy Bot is online as {client.user}!")
    gif_urls = await fetch_gifs_from_github()


@client.event
async def on_message(message):
    global gif_urls

    # Ignore the bot's own messages
    if message.author == client.user:
        return

    # Handle the !reloadgifs command
    if message.content.strip().lower() == "!reloadgifs":
        await message.channel.send("🔄 Reloading GIFs from GitHub...")
        gif_urls = await fetch_gifs_from_github()
        await message.channel.send(f"✅ Done! Loaded **{len(gif_urls)}** GIFs.")
        return

    # Silently refresh GIF list roughly every 100 messages
    if random.randint(1, 100) == 1:
        gif_urls = await fetch_gifs_from_github()

    # 10% chance to jumpscare the user
    if gif_urls and random.random() < JUMPSCARE_CHANCE:
        gif = random.choice(gif_urls)
        await message.reply(gif)


client.run(BOT_TOKEN)
