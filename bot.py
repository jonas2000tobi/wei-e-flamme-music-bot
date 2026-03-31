import os
import json
import asyncio
import disnake
from disnake.ext import commands

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN fehlt.")

intents = disnake.Intents.default()
bot = commands.InteractionBot(intents=intents)
SONGS_FILE = "songs.json"


def load_songs():
    with open(SONGS_FILE, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    return sorted(loaded, key=lambda x: x["id"])


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


music_state = MusicState()


async def ensure_voice(inter: disnake.AppCmdInter):
    if not isinstance(inter.author, disnake.Member):
        return None

    if not inter.author.voice or not inter.author.voice.channel:
        return None

    guild = inter.guild
    if guild is None:
        return None

    target_channel = inter.author.voice.channel
    voice_client = guild.voice_client

    try:
        if voice_client is None:
            voice_client = await target_channel.connect()
        elif voice_client.channel != target_channel:
            await voice_client.move_to(target_channel)
        return voice_client
    except Exception as e:
        print(f"VOICE JOIN FEHLER: {e}")
        return None


async def play_song(inter: disnake.AppCmdInter, index: int):
    async with music_state.lock:
        guild = inter.guild
        if guild is None:
            await inter.edit_original_response("Das geht nur auf einem Server.")
            return

        voice_client = guild.voice_client
        if voice_client is None:
            voice_client = await ensure_voice(inter)
            if voice_client is None:
                await inter.edit_original_response("Konnte Voice-Channel nicht betreten.")
                return

        if index < 0 or index >= len(songs):
            await inter.edit_original_response("Ungültiger Song.")
            return

        song = songs[index]
        music_state.current_index = index
        song_url = song["source"]

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        audio_source = disnake.FFmpegPCMAudio(
            song_url,
            executable=FFMPEG_PATH,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options="-vn",
        )

        voice_client.play(audio_source)
        await inter.edit_original_response(
            f"▶️ Spiele jetzt **#{song['id']} – {song['title']}**"
        )


@bot.event
async def on_ready():
    print(f"Eingeloggt als {bot.user}")
    try:
        if GUILD_ID:
            guild_obj = disnake.Object(id=int(GUILD_ID))
            synced = await bot.sync_commands(test_guilds=[guild_obj.id])
            print(f"Guild-Sync fertig: {len(synced)} Commands")
        else:
            synced = await bot.sync_commands()
            print(f"Global-Sync fertig: {len(synced)} Commands")
    except Exception as e:
        print(f"Sync-Fehler: {e}")


@bot.slash_command(description="Bot joint deinen Voice-Channel.")
async def join(inter: disnake.AppCmdInter):
    await inter.response.defer()
    voice_client = await ensure_voice(inter)
    if voice_client is None:
        await inter.edit_original_response("❌ Konnte nicht joinen.")
        return
    await inter.edit_original_response(f"🔊 Joined **{voice_client.channel.name}**")


@bot.slash_command(description="Bot verlässt Voice.")
async def leave(inter: disnake.AppCmdInter):
    await inter.response.defer()
    guild = inter.guild
    if guild is None or guild.voice_client is None:
        await inter.edit_original_response("Ich bin nicht im Voice.")
        return

    await guild.voice_client.disconnect()
    await inter.edit_original_response("👋 Verlassen")


@bot.slash_command(description="Zeigt Songs.")
async def playlist(inter: disnake.AppCmdInter):
    if not songs:
        await inter.response.send_message("Playlist leer.")
        return

    text = "\n".join([f"{s['id']} – {s['title']}" for s in songs])
    await inter.response.send_message(text)


@bot.slash_command(description="Spielt Song nach Nummer.")
async def play(inter: disnake.AppCmdInter, number: int):
    await inter.response.defer()
    index, song = music_state.get_song_by_number(number)
    if song is None:
        await inter.edit_original_response("Song nicht gefunden.")
        return

    await play_song(inter, index)


@bot.slash_command(description="Nächster Song.")
async def next(inter: disnake.AppCmdInter):
    await inter.response.defer()
    index, song = music_state.get_next_song()
    if song is None:
        await inter.edit_original_response("Keine Songs vorhanden.")
        return

    await play_song(inter, index)


bot.run(DISCORD_TOKEN)
