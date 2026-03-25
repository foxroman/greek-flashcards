#!/usr/bin/env python3
"""
Greek Flashcards - Telegram Bot
Команды:
    /add greek | russian | translit | Greek phrase | Phrase translation
    /list      - все слова от учителя
    /delete t001 - удалить слово
Deploy: Railway.app
"""

import os
import logging
import requests
from datetime import date
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

TELEGRAM_TOKEN       = os.environ["TELEGRAM_TOKEN"]
SUPABASE_URL         = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
FORVO_API_KEY        = os.environ["FORVO_API_KEY"]

HEADERS_SUPABASE = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════

def get_next_word_id() -> str:
    """Получить следующий ID для слова учителя (t001, t002, ...)"""
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


def get_forvo_audio(word: str, language: str = "el") -> bytes | None:
    """Получить аудио произношение с Forvo API"""
    try:
        url = (
            f"https://apifree.forvo.com/key/{FORVO_API_KEY}"
            f"/format/json/action/word-pronunciations"
            f"/word/{word}/language/{language}"
        )
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            logger.error(f"Forvo API error: {response.status_code}")
            return None

        data = response.json()

        if "items" not in data or len(data["items"]) == 0:
            logger.warning(f"No pronunciations found for: {word}")
            return None

        audio_url = data["items"][0]["pathmp3"]
        audio_response = requests.get(audio_url, timeout=15)

        if audio_response.status_code == 200:
            logger.info(f"✓ Audio downloaded for: {word}")
            return audio_response.content

        return None

    except Exception as e:
        logger.error(f"Forvo exception: {e}")
        return None


def upload_to_storage(bucket: str, filename: str, data: bytes, content_type: str) -> str:
    """Загрузить файл в Supabase Storage"""
    r = requests.post(
        f"{SUPABASE_URL}/storage/v1/object/{bucket}/{filename}",
        headers={
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": content_type,
            "x-upsert": "true"
        },
        data=data,
        timeout=30
    )
    if r.status_code not in (200, 201):
        raise Exception(f"Storage upload failed: {r.status_code} {r.text}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{filename}"


def insert_word(word_id, greek, ru, translit, phrase, phrase_ru, audio_word_url):
    """Сохранить слово в таблицу words"""
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/words",
        headers=HEADERS_SUPABASE,
        json={
            "id": word_id,
            "greek": greek,
            "ru": ru,
            "translit": translit,
            "category": "teacher",
            "phrase": phrase,
            "phrase_ru": phrase_ru,
            "added_date": str(date.today()),
            "audio_word_url": audio_word_url
        }
    )
    if r.status_code not in (200, 201):
        raise Exception(f"DB insert failed: {r.status_code} {r.text}")


# ═══════════════════════════════════════════════════════════════
# КОМАНДЫ БОТА
# ═══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🇬🇷 *Greek Flashcards Bot*\n\n"
        "Команды:\n"
        "/add — добавить одно или несколько слов\n"
        "/list — список слов от учителя\n"
        "/delete — удалить слово\n\n"
        "*Одно слово:*\n"
        "`/add σπίτι | дом | spiti | Πάω σπίτι. | Иду домой.`\n\n"
        "*Несколько слов (каждое на новой строке):*\n"
        "`/add\n"
        "σπίτι | дом | spiti | Πάω σπίτι. | Иду домой.\n"
        "γάτος | кот | gátos | Ο γάτος μου. | Мой кот.`",
        parse_mode="Markdown"
    )


async def add_single_word(greek, ru, translit, phrase, phrase_ru) -> str:
    """Добавить одно слово, вернуть строку с результатом"""
    word_id = get_next_word_id()

    audio_word_url = None
    audio_data = get_forvo_audio(greek)
    if audio_data:
        try:
            audio_word_url = upload_to_storage("audio", f"{word_id}.mp3", audio_data, "audio/mpeg")
        except Exception as e:
            logger.error(f"Audio upload failed: {e}")

    insert_word(word_id, greek, ru, translit, phrase, phrase_ru, audio_word_url)

    audio_status = "🔊✓" if audio_word_url else "🔇"
    return f"{audio_status} `{word_id}` {greek} — {ru}"


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Одно слово:   /add σπίτι | дом | spiti | Πάω σπίτι. | Иду домой.
    Несколько:    /add
                  σπίτι | дом | spiti | Πάω σπίτι. | Иду домой.
                  γάτος | кот | gátos | Ο γάτος μου. | Мой кот.
    """
    # Собираем весь текст сообщения после /add
    full_text = update.message.text.partition("/add")[2].strip()

    # Разбиваем на строки, фильтруем пустые
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    if not lines:
        await update.message.reply_text(
            "❌ Формат:\n"
            "`/add σπίτι | дом | spiti | Πάω σπίτι. | Иду домой.`\n\n"
            "Или несколько слов — каждое на новой строке после /add",
            parse_mode="Markdown"
        )
        return

    # Валидируем все строки сначала
    parsed = []
    for i, line in enumerate(lines, 1):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 5:
            await update.message.reply_text(
                f"❌ Строка {i} неверного формата:\n`{line}`\n\nНужно 5 частей через |",
                parse_mode="Markdown"
            )
            return
        parsed.append(parts)

    # Если одно слово
    if len(parsed) == 1:
        greek, ru, translit, phrase, phrase_ru = parsed[0]
        await update.message.reply_text(f"⏳ Добавляю: {greek}...")
        try:
            result = await add_single_word(greek, ru, translit, phrase, phrase_ru)
            await update.message.reply_text(f"✅ {result}", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    # Если несколько слов
    await update.message.reply_text(f"⏳ Добавляю {len(parsed)} слов...")
    results = []
    errors = []

    for greek, ru, translit, phrase, phrase_ru in parsed:
        try:
            result = await add_single_word(greek, ru, translit, phrase, phrase_ru)
            results.append(result)
        except Exception as e:
            errors.append(f"❌ {greek}: {e}")

    summary = [f"✅ Добавлено {len(results)} из {len(parsed)}:\n"]
    summary.extend(results)
    if errors:
        summary.append("\n*Ошибки:*")
        summary.extend(errors)

    await update.message.reply_text("\n".join(summary), parse_mode="Markdown")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все слова от учителя"""
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/words",
        params={
            "category": "eq.teacher",
            "select": "id,greek,ru,added_date",
            "order": "id.asc"
        },
        headers=HEADERS_SUPABASE
    )
    words = r.json()

    if not words:
        await update.message.reply_text("📭 Слов от учителя пока нет.")
        return

    lines = [f"*Слова от учителя ({len(words)}):*\n"]
    for w in words:
        lines.append(f"`{w['id']}` — {w['greek']} ({w['ru']})")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить слово по ID"""
    if not context.args:
        await update.message.reply_text("❌ Формат: `/delete t001`", parse_mode="Markdown")
        return

    word_id = context.args[0].strip()

    # Удаляем из БД
    r = requests.delete(
        f"{SUPABASE_URL}/rest/v1/words",
        params={"id": f"eq.{word_id}"},
        headers=HEADERS_SUPABASE
    )

    if r.status_code in (200, 204):
        # Удаляем аудио из Storage
        requests.delete(
            f"{SUPABASE_URL}/storage/v1/object/audio/{word_id}.mp3",
            headers={
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"
            }
        )
        await update.message.reply_text(f"✅ Слово `{word_id}` удалено.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Ошибка: {r.text}")


# ═══════════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("add",    cmd_add))
    app.add_handler(CommandHandler("list",   cmd_list))
    app.add_handler(CommandHandler("delete", cmd_delete))
    logger.info("🤖 Greek Flashcards Bot started (Forvo API)")
    app.run_polling()
