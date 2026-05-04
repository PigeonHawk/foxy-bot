import discord
from discord import ui
import random
import aiohttp
import os
import asyncio
from collections import deque

# --- CONFIG ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
JUMPSCARE_CHANCE = 0.067

GITHUB_API_URL_GIFS = "https://api.github.com/repos/PigeonHawk/foxy-bot/contents/gifs"
GITHUB_API_URL_MUSIC = "https://api.github.com/repos/PigeonHawk/foxy-bot/contents/music"
GITHUB_RAW_MUSIC = "https://raw.githubusercontent.com/PigeonHawk/foxy-bot/main/music/"

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

client = discord.Client(intents=intents)

gif_urls = []
music_files = []
song_queue = deque()
is_looping = False
gold_saucer_songs = []
active_games = {}

BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
EMOJI = {"rock": "✊", "paper": "✋", "scissors": "✌️"}
TOTAL_SLOTS = 7
CENTER = 3


# ─────────────────────────────────────────────
#  GITHUB FETCHERS
# ─────────────────────────────────────────────

async def fetch_gifs_from_github():
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_API_URL_GIFS) as response:
            if response.status == 200:
                files = await response.json()
                urls = [f["download_url"] for f in files if f["name"].lower().endswith(".gif")]
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
                names = [f["name"] for f in files if f["name"].lower().endswith(".mp3")]
                print(f"✅ Loaded {len(names)} songs from GitHub!")
                return names
            else:
                print(f"❌ Failed to fetch music: HTTP {response.status}")
                return []


# ─────────────────────────────────────────────
#  MUSIC PLAYER
# ─────────────────────────────────────────────

async def play_next(voice_client, channel):
    global is_looping, gold_saucer_songs
    if not song_queue:
        if is_looping and gold_saucer_songs:
            random.shuffle(gold_saucer_songs)
            song_queue.extend(gold_saucer_songs)
        else:
            await channel.send("✅ Queue is empty!")
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
#  FIGHTER HELPERS
# ─────────────────────────────────────────────

def draw_platform(p1pos, p2pos):
    slots = []
    for i in range(TOTAL_SLOTS):
        if i == p1pos and i == p2pos:
            slots.append("[P1P2]")
        elif i == p1pos:
            slots.append("[ P1 ]")
        elif i == p2pos:
            slots.append("[ P2 ]")
        elif i == 0 or i == TOTAL_SLOTS - 1:
            slots.append("[EDGE]")
        elif i == CENTER:
            slots.append("[MID ]")
        else:
            slots.append("[    ]")
    platform = "".join(slots)
    return f"```\n~~~{platform}~~~\n```"


def build_platform_embed(game, title, description, color=0x7F77DD):
    p1 = game["p1_name"]
    p2 = game["p2_name"]
    p1pos = game["p1pos"]
    p2pos = game["p2pos"]

    p1_steps = p1pos
    p2_steps = (TOTAL_SLOTS - 1) - p2pos
    p1_bar = "🟦" * p1_steps + "⬛" * max(0, 3 - p1_steps)
    p2_bar = "🟥" * p2_steps + "⬛" * max(0, 3 - p2_steps)

    embed = discord.Embed(title=title, description=description, color=color)
    embed.add_field(name=f"🟦 {p1}", value=p1_bar, inline=True)
    embed.add_field(name=f"🟥 {p2}", value=p2_bar, inline=True)
    embed.add_field(name="Platform", value=draw_platform(p1pos, p2pos), inline=False)
    return embed


# ─────────────────────────────────────────────
#  CHALLENGE ACCEPT VIEW
# ─────────────────────────────────────────────

class ChallengeView(ui.View):
    def __init__(self, challenger, target, guild_id):
        super().__init__(timeout=30)
        self.challenger = challenger
        self.target = target
        self.guild_id = guild_id
        self.accepted = False

    @ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.target:
            await interaction.response.send_message("❌ This challenge isn't for you!", ephemeral=True)
            return
        self.accepted = True
        self.stop()
        await interaction.response.defer()

    @ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.target:
            await interaction.response.send_message("❌ This challenge isn't for you!", ephemeral=True)
            return
        self.stop()
        await interaction.response.defer()

    async def on_timeout(self):
        pass


# ─────────────────────────────────────────────
#  MOVE SELECTION VIEW
# ─────────────────────────────────────────────

class MoveView(ui.View):
    def __init__(self, game, guild_id):
        super().__init__(timeout=60)
        self.game = game
        self.guild_id = guild_id
        self.p1_move = None
        self.p2_move = None
        self.p1_picked = False
        self.p2_picked = False
        self.is_cpu = game.get("is_cpu", False)

    async def resolve_if_ready(self, interaction):
        if (self.p1_picked and self.p2_picked) or (self.p1_picked and self.is_cpu):
            if self.is_cpu:
                self.p2_move = random.choice(["rock", "paper", "scissors"])
            self.stop()
            await self.resolve_round(interaction.message)

    @ui.button(label="✊ Rock", style=discord.ButtonStyle.secondary, row=0)
    async def rock(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_pick(interaction, "rock")

    @ui.button(label="✋ Paper", style=discord.ButtonStyle.secondary, row=0)
    async def paper(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_pick(interaction, "paper")

    @ui.button(label="✌️ Scissors", style=discord.ButtonStyle.secondary, row=0)
    async def scissors(self, interaction: discord.Interaction, button: ui.Button):
        await self.handle_pick(interaction, "scissors")

    async def handle_pick(self, interaction: discord.Interaction, choice: str):
        game = self.game
        user = interaction.user
        p1 = game["p1"]
        p2 = game.get("p2")
        is_cpu = game.get("is_cpu", False)

        if user == p1 and not self.p1_picked:
            self.p1_move = choice
            self.p1_picked = True
            await interaction.response.send_message(f"✅ Your move is locked in!", ephemeral=True)
        elif not is_cpu and p2 and user == p2 and not self.p2_picked:
            self.p2_move = choice
            self.p2_picked = True
            await interaction.response.send_message(f"✅ Your move is locked in!", ephemeral=True)
        elif user not in [p1, p2]:
            await interaction.response.send_message("❌ You're not in this fight!", ephemeral=True)
            return
        else:
            await interaction.response.send_message("⏳ You already picked!", ephemeral=True)
            return

        # Update status message
        p1_status = "✅ Picked" if self.p1_picked else "⏳ Waiting..."
        p2_name = "CPU" if is_cpu else (game["p2_name"])
        p2_status = "✅ Picked" if (self.p2_picked or is_cpu) else "⏳ Waiting..."

        embed = build_platform_embed(
            game,
            "⚔️ Pick your move!",
            f"🟦 **{game['p1_name']}**: {p1_status}\n🟥 **{p2_name}**: {p2_status}"
        )
        await interaction.message.edit(embed=embed, view=self)
        await self.resolve_if_ready(interaction)

    async def resolve_round(self, message):
        game = self.game
        guild_id = self.guild_id
        p1_move = self.p1_move
        p2_move = self.p2_move
        e1 = EMOJI[p1_move]
        e2 = EMOJI[p2_move]
        p1_name = game["p1_name"]
        p2_name = "CPU" if game.get("is_cpu") else game["p2_name"]

        if p1_move == p2_move:
            title = f"{e1} vs {e2} — Draw!"
            desc = "Nobody moves!"
            color = 0x888780
        elif BEATS[p1_move] == p2_move:
            game["p2pos"] += 1
            title = f"{e1} beats {e2} — {p1_name} wins the round!"
            desc = f"🟥 {p2_name} is pushed back!"
            color = 0x378ADD
        else:
            game["p1pos"] -= 1
            title = f"{e2} beats {e1} — {p2_name} wins the round!"
            desc = f"🟦 {p1_name} is pushed back!"
            color = 0xD85A30

        # Check game over
        if game["p1pos"] < 0:
            embed = build_platform_embed(game, f"💥 {p1_name} fell off the edge!", f"🟥 **{p2_name} wins the match!**", color=0xE24B4A)
            await message.edit(embed=embed, view=None)
            active_games.pop(guild_id, None)
            return

        if game["p2pos"] >= TOTAL_SLOTS:
            embed = build_platform_embed(game, f"💥 {p2_name} fell off the edge!", f"🟦 **{p1_name} wins the match!**", color=0x378ADD)
            await message.edit(embed=embed, view=None)
            active_games.pop(guild_id, None)
            return

        # Next round
        is_cpu = game.get("is_cpu", False)
        p2_status = "🤖 Ready" if is_cpu else "⏳ Waiting..."
        embed = build_platform_embed(game, title, desc, color)
        new_view = MoveView(game, guild_id)
        active_games[guild_id]["view"] = new_view
        await message.edit(embed=embed, view=new_view)

        next_embed = build_platform_embed(
            game,
            "⚔️ Pick your move!",
            f"🟦 **{p1_name}**: ⏳ Waiting...\n🟥 **{p2_name}**: {p2_status}"
        )
        await message.edit(embed=next_embed, view=new_view)

    async def on_timeout(self):
        guild_id = self.guild_id
        if guild_id in active_games:
            active_games.pop(guild_id, None)


# ─────────────────────────────────────────────
#  START GAME HELPER
# ─────────────────────────────────────────────

async def start_game(channel, p1, p2, is_cpu=False, guild_id=None):
    p2_name = "CPU" if is_cpu else p2.display_name
    game = {
        "p1": p1,
        "p2": None if is_cpu else p2,
        "p1_name": p1.display_name,
        "p2_name": p2_name,
        "p1pos": CENTER,
        "p2pos": CENTER,
        "channel": channel,
        "is_cpu": is_cpu,
    }
    active_games[guild_id] = game

    p2_status = "🤖 Ready" if is_cpu else "⏳ Waiting..."
    embed = build_platform_embed(
        game,
        "⚔️ RPS Fighter — Fight!",
        f"🟦 **{p1.display_name}**: ⏳ Waiting...\n🟥 **{p2_name}**: {p2_status}\n\nBoth players press a button to pick secretly!"
    )
    view = MoveView(game, guild_id)
    game["view"] = view
    await channel.send(embed=embed, view=view)


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

    if message.author == client.user:
        return

    content = message.content.strip().lower()
    raw = message.content.strip()

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

    # ── !join (voice) ────────────────────────
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
        saucer_songs = [s for s in music_files if "saucer" in s.lower()]
        if not saucer_songs:
            await message.channel.send("❌ No songs with 'Saucer' in the name found!")
            return
        voice_client = message.guild.voice_client
        if not voice_client:
            channel = message.author.voice.channel
            voice_client = await channel.connect()
            await message.channel.send(f"🦊 Joined **{channel.name}**!")
        elif voice_client.is_playing():
            voice_client.stop()
        is_looping = True
        gold_saucer_songs = saucer_songs.copy()
        song_queue.clear()
        random.shuffle(gold_saucer_songs)
        song_queue.extend(gold_saucer_songs)
        song_names = "\n".join([f"🎵 {s.replace('.mp3', '')}" for s in saucer_songs])
        await message.channel.send(
            f"🎰 **Welcome to the Gold Saucer!** 🎰\nLooping:\n{song_names}\n\nType `!stoploop` to stop or `!leave` to disconnect."
        )
        await play_next(voice_client, message.channel)
        return

    # ── !stoploop ────────────────────────────
    if content == "!stoploop":
        if is_looping:
            is_looping = False
            gold_saucer_songs = []
            await message.channel.send("🔁 Loop stopped!")
        else:
            await message.channel.send("❌ No loop is currently active.")
        return

    # ── !play ────────────────────────────────
    if content.startswith("!play"):
        voice_client = message.guild.voice_client
        if not voice_client:
            await message.channel.send("❌ I'm not in a voice channel! Use `!join` first.")
            return
        if not music_files:
            await message.channel.send("❌ No songs loaded! Try `!reloadmusic`.")
            return
        args = raw[5:].strip()
        if args == "":
            song = random.choice(music_files)
        else:
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

    # ── !fighter (vs CPU) ────────────────────
    if content == "!fighter":
        guild_id = message.guild.id
        if guild_id in active_games:
            await message.channel.send("⚔️ A game is already in progress! Use `!cancelfighter` to cancel it.")
            return
        await start_game(message.channel, message.author, None, is_cpu=True, guild_id=guild_id)
        return

    # ── !fight @user (vs player) ─────────────
    if content.startswith("!fight") and message.mentions:
        guild_id = message.guild.id
        if guild_id in active_games:
            await message.channel.send("⚔️ A game is already in progress! Use `!cancelfighter` to cancel it.")
            return
        target = message.mentions[0]
        if target == message.author:
            await message.channel.send("❌ You can't challenge yourself!")
            return
        if target.bot:
            await message.channel.send("❌ You can't challenge a bot! Use `!fighter` to fight the CPU.")
            return

        challenger = message.author
        challenge_view = ChallengeView(challenger, target, guild_id)
        challenge_msg = await message.channel.send(
            f"⚔️ {challenger.mention} challenges {target.mention} to RPS Fighter!\n"
            f"{target.mention} you have **30 seconds** to accept or decline!",
            view=challenge_view
        )
        await challenge_view.wait()

        if challenge_view.accepted:
            await challenge_msg.edit(content=f"✅ {target.mention} accepted the challenge!", view=None)
            await start_game(message.channel, challenger, target, is_cpu=False, guild_id=guild_id)
        else:
            await challenge_msg.edit(
                content=f"❌ {target.mention} declined or didn't respond in time. Challenge cancelled.",
                view=None
            )
        return

    # ── !hatecrime ───────────────────────────
    if content.startswith("!hatecrime"):
        if message.mentions:
            target = message.mentions[0]
            try:
                await target.send("Hello, how are you? I am under the water. Please help me")
                await message.channel.send(f"✅ Message sent to {target.mention}!")
            except discord.Forbidden:
                await message.channel.send(f"❌ Couldn't DM {target.mention}, they may have DMs disabled.")
        else:
            await message.channel.send("❌ Please mention a user! Example: `!hatecrime @user`")
        return

    # ── !cancelfighter ───────────────────────
    if content == "!cancelfighter":
        guild_id = message.guild.id
        if guild_id in active_games:
            active_games.pop(guild_id)
            await message.channel.send("🛑 Fighter game cancelled.")
        else:
            await message.channel.send("❌ No active fighter game to cancel.")
        return

    # ── Jumpscare ────────────────────────────
    if random.randint(1, 100) == 1:
        gif_urls = await fetch_gifs_from_github()
    if gif_urls and random.random() < JUMPSCARE_CHANCE:
        gif = random.choice(gif_urls)
        await message.reply(gif)


client.run(BOT_TOKEN)
