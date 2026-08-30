import os
import logging
import sqlite3
import random
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# قراءة المتغيرات من البيئة
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DB_NAME = "bot_database.db"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# قاعدة البيانات
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  referrer_id INTEGER,
                  is_verified INTEGER DEFAULT 0,
                  verification_state TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS premium_stickers
                 (file_id TEXT PRIMARY KEY)''')
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def add_user(user_id, referrer_id=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, referrer_id) VALUES (?, ?)", (user_id, referrer_id))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result

def set_user_verified(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET is_verified=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def set_verification_state(user_id, state):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET verification_state=? WHERE user_id=?", (state, user_id))
    conn.commit()
    conn.close()

# وظائف الملصقات المدفوعة
def get_premium_stickers():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT file_id FROM premium_stickers")
    stickers = [row[0] for row in c.fetchall()]
    conn.close()
    return stickers

def add_premium_sticker(file_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO premium_stickers (file_id) VALUES (?)", (file_id,))
    conn.commit()
    conn.close()

def clear_premium_stickers():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM premium_stickers")
    conn.commit()
    conn.close()

# تخزين مؤقت لبيانات التحقق
pending_verifications = {}

def random_text(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def generate_arithmetic():
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    op = random.choice(['+', '-', '*'])
    if op == '+':
        result = a + b
    elif op == '-':
        result = a - b
    else:
        result = a * b
    return f"{a} {op} {b} = ?", result

async def start_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    method = get_setting("verification_method", "text")
    if method == "text":
        code = random_text()
        pending_verifications[user_id] = {"method": "text", "expected": code}
        await context.bot.send_message(chat_id=user_id, text=f"المرحلة الأولى: أرسل النص التالي بالضبط:\n`{code}`", parse_mode="Markdown")
        set_verification_state(user_id, "awaiting_text")
    elif method == "emoji_button":
        emojis = ['🍎', '🍏', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍒']
        correct = random.choice(emojis)
        pending_verifications[user_id] = {"method": "emoji", "correct": correct}
        buttons = []
        options = random.sample(emojis, 4)
        if correct not in options:
            options[0] = correct
        random.shuffle(options)
        for emoji in options:
            buttons.append(InlineKeyboardButton(emoji, callback_data=f"emoji:{emoji}"))
        keyboard = InlineKeyboardMarkup([buttons])
        await context.bot.send_message(chat_id=user_id, text=f"اضغط على الزر الذي يحتوي نفس الإيموجي: {correct}", reply_markup=keyboard)
        set_verification_state(user_id, "awaiting_emoji")
    elif method == "contact":
        keyboard = ReplyKeyboardMarkup([[KeyboardButton("مشاركة جهة الاتصال", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
        await context.bot.send_message(chat_id=user_id, text="لمتابعة التحقق، يرجى مشاركة جهة اتصالك.", reply_markup=keyboard)
        set_verification_state(user_id, "awaiting_contact")
    elif method == "button_text":
        button = InlineKeyboardButton("اضغط للتحقق", callback_data="verify_button")
        keyboard = InlineKeyboardMarkup([[button]])
        await context.bot.send_message(chat_id=user_id, text="اضغط على الزر ثم أرسل النص الذي سيظهر لك.", reply_markup=keyboard)
        set_verification_state(user_id, "awaiting_verify_button")
    elif method == "arithmetic":
        expr, answer = generate_arithmetic()
        pending_verifications[user_id] = {"method": "arithmetic", "answer": answer}
        await context.bot.send_message(chat_id=user_id, text=f"حل العملية الحسابية التالية:\n{expr}")
        set_verification_state(user_id, "awaiting_arithmetic")
    elif method == "sticker":
        stickers = get_premium_stickers()
        if not stickers:
            await context.bot.send_message(chat_id=user_id, text="⚠️ لم يتم إعداد ملصقات للتحقق بعد. حاول لاحقًا.")
            return
        chosen = random.choice(stickers)
        pending_verifications[user_id] = {"method": "sticker", "expected": chosen}
        await context.bot.send_sticker(chat_id=user_id, sticker=chosen)
        await context.bot.send_message(chat_id=user_id, text="أرسل نفس الملصق الذي يظهر لك تمامًا للتحقق.")
        set_verification_state(user_id, "awaiting_sticker")
    else:
        code = random_text()
        pending_verifications[user_id] = {"method": "text", "expected": code}
        await context.bot.send_message(chat_id=user_id, text=f"أرسل النص التالي:\n`{code}`", parse_mode="Markdown")
        set_verification_state(user_id, "awaiting_text")

# معالج /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    referrer_id = None
    if args and args[0].startswith("ref="):
        try:
            referrer_id = int(args[0].split("=")[1])
        except:
            referrer_id = None

    add_user(user_id, referrer_id)
    user = get_user(user_id)
    is_verified = user[2]

    if is_verified:
        bot_username = (await context.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start=ref={user_id}"
        await update.message.reply_text(f"مرحبًا بك! رابط الإحالة الخاص بك:\n{referral_link}")
        return

    if referrer_id is None:
        set_user_verified(user_id)
        bot_username = (await context.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start=ref={user_id}"
        await update.message.reply_text(f"أهلاً بك! أنت لست بحاجة للتحقق.\nرابط الإحالة الخاص بك:\n{referral_link}")
        return

    await update.message.reply_text("مرحبًا! تم تسجيل دخولك عبر رابط إحالة. يجب عليك تجاوز التحقق.")
    await start_verification(update, context, user_id)

# معالج الرسائل النصية
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        return
    is_verified = user[2]
    if is_verified:
        await update.message.reply_text("أنت مستخدم موثوق.")
        return

    state = user[3]
    text = update.message.text

    if state == "awaiting_text":
        pending = pending_verifications.get(user_id)
        if pending and pending["method"] == "text":
            if text == pending["expected"]:
                set_user_verified(user_id)
                set_verification_state(user_id, None)
                await update.message.reply_text("✅ تم التحقق بنجاح! مرحبًا بك في المجموعة.")
            else:
                await update.message.reply_text("النص غير صحيح. حاول مرة أخرى بإرسال النص المطلوب.")
    elif state == "awaiting_arithmetic":
        pending = pending_verifications.get(user_id)
        if pending and pending["method"] == "arithmetic":
            try:
                user_answer = int(text)
                if user_answer == pending["answer"]:
                    set_user_verified(user_id)
                    set_verification_state(user_id, None)
                    await update.message.reply_text("✅ إجابة صحيحة! تم التحقق.")
                else:
                    await update.message.reply_text("إجابة خاطئة. حاول مرة أخرى.")
            except ValueError:
                await update.message.reply_text("يرجى إرسال رقم صحيح.")
    elif state == "awaiting_text_after_verify":
        pending = pending_verifications.get(user_id)
        if pending and pending["method"] == "button_text":
            if text == pending["expected"]:
                set_user_verified(user_id)
                set_verification_state(user_id, None)
                await update.message.reply_text("✅ تم التحقق بنجاح!")
            else:
                await update.message.reply_text("النص غير صحيح. أعد المحاولة.")
    else:
        await update.message.reply_text("لا أعرف ماذا تفعل. استخدم /help للمساعدة.")

# معالج رسائل الاتصال
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        return
    is_verified = user[2]
    if is_verified:
        return

    state = user[3]
    if state == "awaiting_contact" and update.message.contact:
        set_user_verified(user_id)
        set_verification_state(user_id, None)
        await update.message.reply_text("✅ تم التحقق بنجاح عبر جهة الاتصال!")
    else:
        await update.message.reply_text("لم تستلم جهة اتصال. استخدم زر مشاركة جهة الاتصال.")

# معالج استلام الملصقات (يستخدم للتحقق وإضافة الملصقات)
async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        return

    # حالة إضافة ملصقات من المالك
    if user_id == ADMIN_ID and user[3] == "awaiting_sticker_add":
        file_id = update.message.sticker.file_id
        saved_before = len(get_premium_stickers())
        add_premium_sticker(file_id)
        saved_count = len(get_premium_stickers())
        if saved_count == saved_before:
            await update.message.reply_text(
                f"هذا الملصق مكرر. المحفوظ حاليًا: {saved_count}/5. أرسل ملصقًا مختلفًا."
            )
        elif saved_count < 5:
            await update.message.reply_text(
                f"تم حفظ الملصق {saved_count}/5. أرسل الملصق التالي."
            )
        else:
            set_verification_state(user_id, None)
            await update.message.reply_text(
                "✅ اكتمل حفظ الملصقات المدفوعة 5/5، وأصبحت جاهزة لاستخدامها في التحقق."
            )
        return

    # التحقق من ملصق المستخدم
    if user[3] == "awaiting_sticker":
        file_id = update.message.sticker.file_id
        pending = pending_verifications.get(user_id)
        if pending and pending["method"] == "sticker":
            # نتحقق من أن الملف المرسل موجود في قائمة الملصقات المحددة (أي تطابق مع المطلوب)
            if file_id == pending["expected"]:
                set_user_verified(user_id)
                set_verification_state(user_id, None)
                await update.message.reply_text("✅ تم التحقق بنجاح!")
            else:
                await update.message.reply_text("❌ الملصق غير صحيح. حاول مرة أخرى.")
                # إعادة إرسال نفس الملصق
                await context.bot.send_sticker(chat_id=user_id, sticker=pending["expected"])
                await context.bot.send_message(chat_id=user_id, text="أرسل الملصق المطلوب.")
        else:
            await update.message.reply_text("غير متوقع.")
        return

    # رسالة عادية
    await update.message.reply_text("أرسل ملصق؟")

# معالج أزرار (CallbackQuery)
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("خطأ: المستخدم غير مسجل.")
        return
    is_verified = user[2]
    if is_verified:
        await query.edit_message_text("أنت موثق بالفعل.")
        return

    data = query.data
    state = user[3]

    if state == "awaiting_emoji":
        if data.startswith("emoji:"):
            chosen_emoji = data.split(":", 1)[1]
            pending = pending_verifications.get(user_id)
            if pending and pending["method"] == "emoji":
                if chosen_emoji == pending["correct"]:
                    set_user_verified(user_id)
                    set_verification_state(user_id, None)
                    await query.edit_message_text("✅ تم التحقق بنجاح!")
                else:
                    await query.edit_message_text("إيموجي غير صحيح. أعد المحاولة.")
                    await start_verification(update, context, user_id)
    elif state == "awaiting_verify_button":
        if data == "verify_button":
            code = random_text()
            pending_verifications[user_id] = {"method": "button_text", "expected": code}
            await query.edit_message_text(f"الآن أرسل النص التالي:\n`{code}`", parse_mode="Markdown")
            set_verification_state(user_id, "awaiting_text_after_verify")
    else:
        await query.edit_message_text("لا يوجد إجراء مطلوب.")

# أمر المالك لاختيار طريقة التحقق
async def set_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("عذرًا، هذا الأمر للمالك فقط.")
        return

    keyboard = [
        [InlineKeyboardButton("نص كتابي", callback_data="set:text")],
        [InlineKeyboardButton("زر إيموجي", callback_data="set:emoji_button")],
        [InlineKeyboardButton("مشاركة جهة اتصال", callback_data="set:contact")],
        [InlineKeyboardButton("زر + نص", callback_data="set:button_text")],
        [InlineKeyboardButton("عملية حسابية", callback_data="set:arithmetic")],
        [InlineKeyboardButton("ملصقات مدفوعة", callback_data="set:sticker")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر طريقة التحقق المطلوبة:", reply_markup=reply_markup)

# معالج اختيار طريقة التحقق
async def handle_set_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("غير مصرح.")
        return

    data = query.data
    if data.startswith("set:"):
        method = data.split(":", 1)[1]
        set_setting("verification_method", method)
        if method == "sticker":
            await query.edit_message_text("تم اختيار التحقق بالملصقات المدفوعة.\nالآن أرسل الأمر /addsticker لتسجيل 5 ملصقات.")
        else:
            await query.edit_message_text(f"تم تعيين طريقة التحقق إلى: {method}")

# أمر إضافة الملصقات (للمالك)
async def add_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("عذرًا، هذا الأمر للمالك فقط.")
        return
    clear_premium_stickers()
    set_verification_state(ADMIN_ID, "awaiting_sticker_add")
    await update.message.reply_text("أرسل الآن 5 ملصقات (مدفوعة) واحدة تلو الأخرى.")

# معالج الأوامر العامة
async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("هذا بوت إحالات وتحقق. أرسل /start للحصول على رابط الإحالة الخاص بك.\n\nللمالك: /setverify لاختيار طريقة التحقق، و /addsticker لإضافة ملصقات التحقق.")

# الدالة الرئيسية
def main():
    if not BOT_TOKEN or not ADMIN_ID:
        logger.error("تأكد من تعيين BOT_TOKEN و ADMIN_ID في متغيرات البيئة.")
        return
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help))
    app.add_handler(CommandHandler("setverify", set_verify))
    app.add_handler(CommandHandler("addsticker", add_sticker))
    app.add_handler(CallbackQueryHandler(handle_set_verify_callback, pattern="^set:"))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
