import os
import json
import asyncio

import discord
from discord import app_commands
from discord.ext import commands


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt.")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

SONGS_FILE = "songs.json"


def load_songs():
    with open(SONGS_FILE, "r", encoding="utf-8") as f:
        loaded_songs = json.load(f)
    return sorted(loaded_songs, key=lambda x: x["id"])


songs = load_songs()


class MusicState:
    def __init__(self):
        self.current_index = None
        self.lock = asyncio.Lock()

    def get_song_by_number(self, number: int):
        for idx, song in enumerate(songs):
            if song["id"] == number:
                return idx, song
        return None, None

    def get_next_song(self):
        if not songs:
            return None, None
        if self.current_index is None:
            return 0, songs[0]
        next_index = (self.current_index + 1) % len(songs)
        return next_index, songs[next_index]

    def get_previous_song(self):
        if not songs:
            return None, None
        if self.current_index is None:
            return 0, songs[0]
        prev_index = (self.current_index - 1) % len(songs)
        return prev_index, songs[prev_index]


music_state = MusicState()


# 🔥 WICHTIG: stabiler Voice Join
async def ensure_voice(interaction: discord.Interaction):
    if not interaction.user or not isinstance(interaction.user, discord.Member):
        return None

    voice_state = interaction.user.voice
    if voice_state is None or voice_state.channel is None:
        return None

    guild = interaction.guild
    if guild is None:
        return None

    target_channel = voice_state.channel
    voice_client = guild.voice_client

    try:
        if voice_client is None:
            voice_client = await target_channel.connect(timeout=15.0, reconnect=False)
        elif voice_client.channel != target_channel:
            await voice_client.move_to(target_channel)

        return voice_client
    except Exception as e:
        print(f"VOICE JOIN FEHLER: {e}")
        return None


async def play_song(interaction: discord.Interaction, index: int):
    async with music_state.lock:
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Das geht nur auf einem Server.")
            return

        voice_client = guild.voice_client
        if voice_client is None:
            voice_client = await ensure_voice(interaction)
            if voice_client is None:
                await interaction.followup.send("Konnte Voice-Channel nicht betreten.")
                return

        if index < 0 or index >= len(songs):
            await interaction.followup.send("Ungültiger Song.")
            return

        song = songs[index]
        music_state.current_index = index
        song_url = song["source"]

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        source = discord.FFmpegPCMAudio(
            song_url,
            executable=FFMPEG_PATH,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options="-vn",
        )

        voice_client.play(source)

        await interaction.followup.send(
            f"▶️ Spiele jetzt **#{song['id']} – {song['title']}**"
        )


@bot.event
async def on_ready():
    print(f"Eingeloggt als {bot.user}")

    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"Guild-Sync fertig: {len(synced)} Commands")
        else:
            synced = await bot.tree.sync()
            print(f"Global-Sync fertig: {len(synced)} Commands")
    except Exception as e:
        print(f"Sync-Fehler: {e}")


# 🔥 FIX: defer damit Discord nicht abkackt
@bot.tree.command(name="join", description="Bot joint deinen Voice-Channel.")
async def join(interaction: discord.Interaction):
    await interaction.response.defer()

    voice_client = await ensure_voice(interaction)

    if voice_client is None:
        await interaction.followup.send("❌ Konnte nicht joinen.")
        return

    await interaction.followup.send(f"🔊 Joined **{voice_client.channel.name}**")


@bot.tree.command(name="leave", description="Bot verlässt Voice.")
async def leave(interaction: discord.Interaction):
    await interaction.response.defer()

    guild = interaction.guild
    if guild is None or guild.voice_client is None:
        await interaction.followup.send("Ich bin nicht im Voice.")
        return

    await guild.voice_client.disconnect()
    await interaction.followup.send("👋 Verlassen")


@bot.tree.command(name="playlist", description="Zeigt Songs.")
async def playlist(interaction: discord.Interaction):
    lines = [f"{s['id']} – {s['title']}" for s in songs]
    await interaction.response.send_message("\n".join(lines))


@bot.tree.command(name="play", description="Spielt Song.")
async def play(interaction: discord.Interaction, number: int):
    await interaction.response.defer()

    index, song = music_state.get_song_by_number(number)
    if song is None:
        await interaction.followup.send("Song nicht gefunden.")
        return

    await play_song(interaction, index)


@bot.tree.command(name="next", description="Next Song")
async def next_song(interaction: discord.Interaction):
    await interaction.response.defer()
    index, song = music_state.get_next_song()
    await play_song(interaction, index)


@bot.tree.command(name="prev", description="Previous Song")
async def prev_song(interaction: discord.Interaction):
    await interaction.response.defer()
    index, song = music_state.get_previous_song()
    await play_song(interaction, index)


@bot.tree.command(name="stop", description="Stop")
async def stop(interaction: discord.Interaction):
    guild = interaction.guild
    if guild and guild.voice_client:
        guild.voice_client.stop()
    await interaction.response.send_message("⏹️ Stop")


bot.run(DISCORD_TOKEN)
