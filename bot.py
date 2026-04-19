#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import asyncio
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from pptx import Presentation

# ---------- الإعدادات ----------
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("الرجاء تعيين BOT_TOKEN كمتغير بيئة")

# إعداد التسجيل
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# قاموس مؤقت لحفظ الملفات
user_files = {}

# ---------- دوال معالجة PPTX ----------
def crop_pptx_from_bottom(file_bytes: bytes, crop_percent: int) -> BytesIO:
    prs = Presentation(BytesIO(file_bytes))
    original_width = prs.slide_width
    original_height = prs.slide_height
    new_height = int(original_height * (1 - crop_percent / 100.0))
    prs.slide_width = original_width
    prs.slide_height = new_height
    output = BytesIO()
    prs.save(output)
    output.seek(0)
    return output

# ---------- أوامر البوت ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 أهلاً بك في بوت قص شرائح البوربوينت!\n\n"
        "📤 أرسل لي ملف PPTX لتبدأ.\n"
        "✂️ بعدها ستختار نسبة القص من الأسفل (1% - 80%)."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    document = update.message.document

    if not document.file_name.lower().endswith(".pptx"):
        await update.message.reply_text("❌ الملف يجب أن يكون بصيغة .pptx فقط.")
        return

    file = await context.bot.get_file(document.file_id)
    file_bytes = await file.download_as_bytearray()
    user_files[user_id] = bytes(file_bytes)

    keyboard = [
        [
            InlineKeyboardButton("10%", callback_data="crop_10"),
            InlineKeyboardButton("20%", callback_data="crop_20"),
            InlineKeyboardButton("30%", callback_data="crop_30"),
        ],
        [
            InlineKeyboardButton("40%", callback_data="crop_40"),
            InlineKeyboardButton("50%", callback_data="crop_50"),
            InlineKeyboardButton("60%", callback_data="crop_60"),
        ],
        [
            InlineKeyboardButton("70%", callback_data="crop_70"),
            InlineKeyboardButton("80%", callback_data="crop_80"),
        ],
        [InlineKeyboardButton("✏️ إدخال نسبة يدوية", callback_data="manual_crop")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"✅ تم استلام الملف: `{document.file_name}`\n\n"
        "🔽 اختر نسبة القص من الأسفل:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if user_id not in user_files:
        await query.edit_message_text("⚠️ لم يتم العثور على ملف. أرسل ملف PPTX أولاً.")
        return

    if data == "manual_crop":
        await query.edit_message_text(
            "📝 الرجاء إرسال النسبة المطلوبة (رقم بين 1 و 80) في رسالة نصية:"
        )
        context.user_data["awaiting_crop_value"] = True
        return

    percent = int(data.split("_")[1])
    await process_crop(update, context, user_id, percent)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.user_data.get("awaiting_crop_value"):
        return

    text = update.message.text.strip()
    try:
        percent = int(text)
        if percent < 1 or percent > 80:
            await update.message.reply_text("❌ النسبة يجب أن تكون بين 1 و 80. حاول مجدداً:")
            return
    except ValueError:
        await update.message.reply_text("❌ الرجاء إرسال رقم صحيح بين 1 و 80:")
        return

    context.user_data["awaiting_crop_value"] = False
    await process_crop(update, context, user_id, percent, is_manual=True)

async def process_crop(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       user_id: int, percent: int, is_manual: bool = False):
    file_bytes = user_files.get(user_id)
    if not file_bytes:
        if is_manual:
            await update.message.reply_text("⚠️ انتهت صلاحية الملف. أرسل PPTX مجدداً.")
        else:
            await update.callback_query.edit_message_text("⚠️ انتهت صلاحية الملف. أرسل PPTX مجدداً.")
        return

    if is_manual:
        msg = await update.message.reply_text("⏳ جاري معالجة الملف...")
    else:
        msg = await update.callback_query.edit_message_text("⏳ جاري معالجة الملف...")

    try:
        loop = asyncio.get_event_loop()
        output_stream = await loop.run_in_executor(
            None, crop_pptx_from_bottom, file_bytes, percent
        )

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=output_stream,
            filename=f"cropped_{percent}percent.pptx",
            caption=f"✅ تم قص {percent}% من أسفل الشرائح بنجاح!"
        )
        await msg.delete()
    except Exception as e:
        logger.error(f"خطأ أثناء معالجة الملف: {e}")
        error_text = f"❌ حدث خطأ أثناء المعالجة: {str(e)}"
        if is_manual:
            await msg.edit_text(error_text)
        else:
            await msg.edit_text(error_text)
    finally:
        user_files.pop(user_id, None)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="استثناء غير معالج:", exc_info=context.error)

# ---------- الدالة الرئيسية ----------
def main():
    # استخدام ApplicationBuilder مباشرة لتجنب أي تعارض
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)

    logger.info("🤖 البوت يعمل الآن...")
    application.run_polling()

if __name__ == "__main__":
    main()
