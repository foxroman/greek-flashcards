#!/usr/bin/env python3
"""
Greek Flashcards — Telegram Bot
--------------------------------
Команды:
  /add σπίτι | дом | Πάω σπίτι τώρα. | Иду домой сейчас.
  /list      — все слова от учителя
  /delete t001 — удалить слово

Деплой: Railway.app
"""

import os
import re
import requests
from datetime import date
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN       = os.environ["TELEGRAM_TOKEN"]
ELEVENLABS_API_KEY   = os.environ["ELEVENLABS_API_KEY"]
VOICE_ID             = "JrrE7QTGDmQKQuUnqk7H"
MODEL_ID             = "eleven_multilingual_v2"

SUPABASE_URL         = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

HEADERS_SUPABASE = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def get_next_word_id() -> str:
    """Получить следующий ID вида t001, t002..."""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/words",
        params={"category": "eq.teacher", "select": "id", "order": "id.desc", "limit": "1"},
        headers=HEADERS_SUPABASE
    )
    rows = r.json()
    if not rows:
        return "t001"
    last = rows[0]["id"]  # например t007
    num = int(last[1:]) + 1
    return f"t{num:03d}"


def generate_mp3(text: str) -> bytes:
    """Генерация MP3 через ElevenLabs."""
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        },
        json={
            "text": text,
            "model_id": MODEL_ID,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
        }
    )
    r.raise_for_status()
    return r.content


def generate_image(word_ru: str) -> bytes:
    """Генерация картинки через Pollinations.ai."""
    prompt = f"simple illustration of {word_ru}, minimalist, flat design, no text"
    url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?width=512&height=512&nologo=true"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content


def upload_to_storage(bucket: str, filename: str, data: bytes, content_type: str) -> str:
    """Загрузить файл в Supabase Storage, вернуть публичный URL."""
    r = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{filename}",
        headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": content_type,
            "x-upsert": "true"
        },
        data=data
    )
    r.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{filename}"


def insert_word(word_id: str, greek: str, ru: str, phrase: str, phrase_ru: str,
                audio_word_url: str, audio_phrase_url: str, image_url: str):
    """Вставить слово в таблицу words."""
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/words",
        headers=HEADERS_SUPABASE,
        json={
            "id": word_id,
            "greek": greek,
            "ru": ru,
            "category": "teacher",
            "phrase": phrase,
            "phrase_ru": phrase_ru,
            "added_date": str(date.today()),
            "audio_word_url": audio_word_url,
            "audio_phrase_url": audio_phrase_url,
            "image_url": image_url
        }
    )
    r.raise_for_status()


# ─── КОМАНДЫ ──────────────────────────────────────────────────────────────────

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /add σπίτι | дом | Πάω σπίτι τώρα. | Иду домой сейчас.
    """
    text = " ".join(context.args)
    parts = [p.strip() for p in text.split("|")]

    if len(parts) != 4:
        await update.message.reply_text(
            "❌ Формат:\n/add греческое | русское | Фраза на греческом | Перевод фразы"
        )
        return

    greek, ru, phrase, phrase_ru = parts
    word_id = get_next_word_id()

    await update.message.reply_text(f"⏳ Добавляю слово {word_id}: {greek} — {ru}...")

    try:
        # 1. MP3 слова
        await update.message.reply_text("🎤 Генерирую озвучку слова...")
        audio_word = generate_mp3(greek)
        audio_word_url = upload_to_storage("audio", f"{word_id}_word.mp3", audio_word, "audio/mpeg")

        # 2. MP3 фразы
        await update.message.reply_text("🎤 Генерирую озвучку фразы...")
        audio_phrase = generate_mp3(phrase)
        audio_phrase_url = upload_to_storage("audio", f"{word_id}_phrase.mp3", audio_phrase, "audio/mpeg")

        # 3. Картинка
        await update.message.reply_text("🖼 Генерирую картинку...")
        image_data = generate_image(ru)
        image_url = upload_to_storage("images", f"{word_id}.jpg", image_data, "image/jpeg")

        # 4. Запись в БД
        insert_word(word_id, greek, ru, phrase, phrase_ru, audio_word_url, audio_phrase_url, image_url)

        await update.message.reply_text(
            f"✅ Слово добавлено!\n\n"
            f"🆔 {word_id}\n"
            f"🇬🇷 {greek}\n"
            f"🇷🇺 {ru}\n"
            f"💬 {phrase}\n"
            f"📝 {phrase_ru}"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/list — показать все слова от учителя"""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/words",
        params={"category": "eq.teacher", "select": "id,greek,ru,added_date", "order": "id.asc"},
        headers=HEADERS_SUPABASE
    )
    words = r.json()

    if not words:
        await update.message.reply_text("📭 Слов от учителя пока нет.")
        return

    lines = [f"`{w['id']}` {w['greek']} — {w['ru']} ({w['added_date']})" for w in words]
    await update.message.reply_text(
        f"📚 Слова от учителя ({len(words)} шт.):\n\n" + "\n".join(lines),
        parse_mode="Markdown"
    )


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/delete t001 — удалить слово"""
    if not context.args:
        await update.message.reply_text("❌ Укажи ID: /delete t001")
        return

    word_id = context.args[0].strip()
    r = requests.delete(
        f"{SUPABASE_URL}/rest/v1/words",
        params={"id": f"eq.{word_id}"},
        headers=HEADERS_SUPABASE
    )

    if r.status_code in (200, 204):
        await update.message.reply_text(f"🗑 Слово {word_id} удалено.")
    else:
        await update.message.reply_text(f"❌ Ошибка: {r.text}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Greek Flashcards Bot\n\n"
        "Команды:\n"
        "/add σπίτι | дом | Πάω σπίτι τώρα. | Иду домой сейчас.\n"
        "/list — все слова от учителя\n"
        "/delete t001 — удалить слово"
    )


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("delete", cmd_delete))
    print("🤖 Bot started...")
    app.run_polling()
