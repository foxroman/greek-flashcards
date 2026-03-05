#!/usr/bin/env python3
"""
Greek Flashcards - Telegram Bot
Команды:
    /add greek | russian | Phrase in greek | Phrase translation
    /list      - all teacher words
    /delete t001 - delete word
Deploy: Railway.app
"""

import os
import requests
from datetime import date
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
VOICE_ID           = "JrrE7QTGDmQKQuUnqk7H"
MODEL_ID           = "eleven_multilingual_v2"
SUPABASE_URL       = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
UNSPLASH_ACCESS_KEY  = os.environ["UNSPLASH_ACCESS_KEY"]

HEADERS_SUPABASE = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}

def get_next_word_id() -> str:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/words",
        params={"category": "eq.teacher", "select": "id", "order": "id.desc", "limit": "1"},
        headers=HEADERS_SUPABASE
    )
    rows = r.json()
    if not rows:
        return "t001"
    last = rows[0]["id"]
    num = int(last[1:]) + 1
    return f"t{num:03d}"

def generate_mp3(text: str) -> bytes:
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={"text": text, "model_id": MODEL_ID, "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    )
    r.raise_for_status()
    return r.content

def generate_image(word_ru: str, word_greek: str) -> bytes:
    for query in [word_ru, word_greek]:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 1, "orientation": "squarish"},
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=15
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            img_url = results[0]["urls"]["small"]
            img_r = requests.get(img_url, timeout=20)
            img_r.raise_for_status()
            return img_r.content
    raise Exception("Unsplash: image not found")

def upload_to_storage(bucket: str, filename: str, data: bytes, content_type: str) -> str:
    r = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{filename}",
        headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "Content-Type": content_type, "x-upsert": "true"},
        data=data
    )
    r.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{filename}"

def insert_word(word_id, greek, ru, phrase, phrase_ru, audio_word_url, audio_phrase_url, image_url):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/words",
        headers=HEADERS_SUPABASE,
        json={"id": word_id, "greek": greek, "ru": ru, "category": "teacher", "phrase": phrase, "phrase_ru": phrase_ru, "added_date": str(date.today()), "audio_word_url": audio_word_url, "audio_phrase_url": audio_phrase_url, "image_url": image_url}
    )
    r.raise_for_status()

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 4:
        await update.message.reply_text("Format: /add greek | russian | Greek phrase | Translation")
        return
    greek, ru, phrase, phrase_ru = parts
    word_id = get_next_word_id()
    await update.message.reply_text(f"Adding {word_id}: {greek} - {ru}...")
    try:
        await update.message.reply_text("Generating word audio...")
        audio_word = generate_mp3(greek)
        audio_word_url = upload_to_storage("audio", f"{word_id}_word.mp3", audio_word, "audio/mpeg")
        await update.message.reply_text("Generating phrase audio...")
        audio_phrase = generate_mp3(phrase)
        audio_phrase_url = upload_to_storage("audio", f"{word_id}_phrase.mp3", audio_phrase, "audio/mpeg")
        await update.message.reply_text("Finding image on Unsplash...")
        image_data = generate_image(ru, greek)
        image_url = upload_to_storage("images", f"{word_id}.jpg", image_data, "image/jpeg")
        insert_word(word_id, greek, ru, phrase, phrase_ru, audio_word_url, audio_phrase_url, image_url)
        await update.message.reply_text(f"✅ Word added!\n\nID: {word_id}\n🇬🇷 {greek}\n🇷🇺 {ru}\n💬 {phrase}\n📝 {phrase_ru}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/words", params={"category": "eq.teacher", "select": "id,greek,ru,added_date", "order": "id.asc"}, headers=HEADERS_SUPABASE)
    words = r.json()
    if not words:
        await update.message.reply_text("No teacher words yet.")
        return
    lines = [f"{w['id']} {w['greek']} - {w['ru']} ({w['added_date']})" for w in words]
    await update.message.reply_text(f"Teacher words ({len(words)}):\n\n" + "\n".join(lines))

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delete t001")
        return
    word_id = context.args[0].strip()
    r = requests.delete(f"{SUPABASE_URL}/rest/v1/words", params={"id": f"eq.{word_id}"}, headers=HEADERS_SUPABASE)
    if r.status_code in (200, 204):
        await update.message.reply_text(f"Deleted {word_id}")
    else:
        await update.message.reply_text(f"Error: {r.text}")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Greek Flashcards Bot\n/add greek | russian | phrase | translation\n/list\n/delete t001")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("delete", cmd_delete))
    print("Bot started...")
    app.run_polling()
