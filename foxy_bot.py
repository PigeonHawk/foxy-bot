import discord
import random
import aiohttp
import os
# --- CONFIG ---
BOT_TOKEN = "MTQ5OTk4NzUyMzA3Njc1NTU5Nw.GwyIGb.VQGgr9VnuK5LPYA-40i48tWPRJA9N-sjyBXTJk"
JUMPSCARE_CHANCE = 0.10

# GitHub API URL pointing to your gifs folder
# Replace YOUR_USERNAME and YOUR_REPO with your actual GitHub info
GITHUB_API_URL = "GITHUB_API_URL = "https://api.github.com/repos/PigeonHawk/foxy-bot/contents/gifs"

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
gif_urls = []  # Cached list of GIF URLs


async def fetch_gifs_from_github():
    """Fetches the list of GIFs from your GitHub repo."""
    async with aiohttp.ClientSession() as session:
        async with session.get(GITHUB_API_URL) as response:
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
