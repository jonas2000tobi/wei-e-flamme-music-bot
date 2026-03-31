import os
import json
import asyncio

import discord
from discord import app_commands
from discord.ext import commands


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # optional für schnellere Command-Syncs beim Testen
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt.")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

SONGS_FILE = "songs.json"


def load_songs():
    with open(SONGS_FILE, "r", encoding="utf-8") as f:
        songs = json.load(f)

    songs = sorted(songs, key=lambda x: x["id"])
    return songs


songs = load_songs()


class MusicState:
    def __init__(self):
        self.current_index = None
        self.last_text_channel = None
        self.lock = asyncio.Lock()

    def get_song_by_number(self, number: int):
        for idx, song in enumerate(songs):
            if song["id"] == number:
                return idx, song
        return None, None

    def get_current_song(self):
        if self.current_index is None:
            return None
        if 0 <= self.current_index < len(songs):
            return songs[self.current_index]
        return None

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


async def ensure_voice(interaction: discord.Interaction):
    if not interaction.user or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Konnte deinen Voice-Status nicht prüfen.", ephemeral=True)
        return None

    voice_state = interaction.user.voice
    if voice_state is None or voice_state.channel is None:
        await interaction.response.send_message("Du bist in keinem Voice-Channel.", ephemeral=True)
        return None

    target_channel = voice_state.channel
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("Das geht nur auf einem Server.", ephemeral=True)
        return None

    voice_client = guild.voice_client

    if voice_client is None:
        voice_client = await target_channel.connect()
    else:
        if voice_client.channel != target_channel:
            await voice_client.move_to(target_channel)

    music_state.last_text_channel = interaction.channel
    return voice_client


async def play_song(interaction: discord.Interaction, index: int):
    async with music_state.lock:
        guild = interaction.guild
        if guild is None:
            if not interaction.response.is_done():
                await interaction.response.send_message("Das geht nur auf einem Server.", ephemeral=True)
            return

        voice_client = guild.voice_client
        if voice_client is None:
            voice_client = await ensure_voice(interaction)
            if voice_client is None:
                return

        if index < 0 or index >= len(songs):
            if not interaction.response.is_done():
                await interaction.response.send_message("Ungültiger Song-Index.", ephemeral=True)
            return

        song = songs[index]
        music_state.current_index = index
        music_state.last_text_channel = interaction.channel

        song_url = song["source"]

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        source = discord.FFmpegPCMAudio(
            song_url,
            executable=FFMPEG_PATH,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options="-vn"
        )

        def after_playback(error):
            if error:
                print(f"Playback-Fehler: {error}")

        voice_client.play(source, after=after_playback)

        message = f"▶️ Spiele jetzt **#{song['id']} – {song['title']}**"
        if interaction.response.is_done():
            await interaction.followup.send(message)
        else:
            await interaction.response.send_message(message)


@bot.event
async def on_ready():
    print(f"Eingeloggt als {bot.user}")

    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"Guild-Sync fertig: {len(synced)} Commands")
        else:
            synced = await bot.tree.sync()
            print(f"Global-Sync fertig: {len(synced)} Commands")
    except Exception as e:
        print(f"Sync-Fehler: {e}")


def guild_only_command():
    if GUILD_ID:
        return app_commands.guilds(discord.Object(id=int(GUILD_ID)))
    return lambda f: f


@guild_only_command()
@bot.tree.command(name="join", description="Bot joint deinen aktuellen Voice-Channel.")
async def join(interaction: discord.Interaction):
    voice_client = await ensure_voice(interaction)
    if voice_client is None:
        return

    if interaction.response.is_done():
        await interaction.followup.send(f"🔊 Ich bin jetzt in **{voice_client.channel.name}**.")
    else:
        await interaction.response.send_message(f"🔊 Ich bin jetzt in **{voice_client.channel.name}**.")


@guild_only_command()
@bot.tree.command(name="leave", description="Bot verlässt den Voice-Channel.")
async def leave(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None or guild.voice_client is None:
        await interaction.response.send_message("Ich bin in keinem Voice-Channel.", ephemeral=True)
        return

    await guild.voice_client.disconnect()
    await interaction.response.send_message("👋 Voice-Channel verlassen.")


@guild_only_command()
@bot.tree.command(name="playlist", description="Zeigt die komplette Musikliste.")
async def playlist(interaction: discord.Interaction):
    if not songs:
        await interaction.response.send_message("Die Playlist ist leer.", ephemeral=True)
        return

    lines = [f"**#{song['id']}** – {song['title']}" for song in songs]
    text = "\n".join(lines)

    if len(text) > 1900:
        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 1900:
                chunks.append(current)
                current = line
            else:
                current += ("\n" if current else "") + line
        if current:
            chunks.append(current)

        await interaction.response.send_message(chunks[0])
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)
    else:
        await interaction.response.send_message(text)


@guild_only_command()
@bot.tree.command(name="play", description="Spielt einen Song nach Nummer ab.")
@app_commands.describe(number="Songnummer aus der Playlist, z. B. 1 oder 2")
async def play(interaction: discord.Interaction, number: int):
    index, song = music_state.get_song_by_number(number)
    if song is None:
        await interaction.response.send_message("Songnummer nicht gefunden.", ephemeral=True)
        return

    await play_song(interaction, index)


@guild_only_command()
@bot.tree.command(name="next", description="Spielt den nächsten Song.")
async def next_song(interaction: discord.Interaction):
    index, song = music_state.get_next_song()
    if song is None:
        await interaction.response.send_message("Keine Songs in der Liste.", ephemeral=True)
        return

    await play_song(interaction, index)


@guild_only_command()
@bot.tree.command(name="prev", description="Spielt den vorherigen Song.")
async def prev_song(interaction: discord.Interaction):
    index, song = music_state.get_previous_song()
    if song is None:
        await interaction.response.send_message("Keine Songs in der Liste.", ephemeral=True)
        return

    await play_song(interaction, index)


@guild_only_command()
@bot.tree.command(name="stop", description="Stoppt die Wiedergabe.")
async def stop(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None or guild.voice_client is None:
        await interaction.response.send_message("Ich bin in keinem Voice-Channel.", ephemeral=True)
        return

    vc = guild.voice_client
    if vc.is_playing() or vc.is_paused():
        vc.stop()
        await interaction.response.send_message("⏹️ Wiedergabe gestoppt.")
    else:
        await interaction.response.send_message("Es läuft gerade nichts.", ephemeral=True)


@guild_only_command()
@bot.tree.command(name="pause", description="Pausiert die Wiedergabe.")
async def pause(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None or guild.voice_client is None:
        await interaction.response.send_message("Ich bin in keinem Voice-Channel.", ephemeral=True)
        return

    vc = guild.voice_client
    if vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Pausiert.")
    else:
        await interaction.response.send_message("Es läuft gerade nichts.", ephemeral=True)


@guild_only_command()
@bot.tree.command(name="resume", description="Setzt die Wiedergabe fort.")
async def resume(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None or guild.voice_client is None:
        await interaction.response.send_message("Ich bin in keinem Voice-Channel.", ephemeral=True)
        return

    vc = guild.voice_client
    if vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Wiedergabe fortgesetzt.")
    else:
        await interaction.response.send_message("Es ist nichts pausiert.", ephemeral=True)


bot.run(DISCORD_TOKEN)
