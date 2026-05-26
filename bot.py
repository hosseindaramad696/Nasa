import os
import logging
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from database import (
    init_db, upsert_user, get_user, is_blocked, set_blocked,
    get_blocked_users, add_coins, get_coins, log_message, get_stats,
    update_location, get_nearby_users, add_referral, get_referral_count,
    update_bio, search_users,
    create_payment, get_payment, confirm_payment, reject_payment, get_pending_payments
)

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID    = int(os.environ.get("ADMIN_ID", "0"))
CARD_NUMBER = os.environ.get("CARD_NUMBER", "6219-8610-XXXX-XXXX")  # شماره کارت شما
CARD_NAME   = os.environ.get("CARD_NAME", "نام صاحب کارت")

# قیمت‌گذاری سکه
COIN_PACKAGES = [
    {"coins": 10,  "toman": 20_000,  "label": "۱۰ سکه — ۲۰٬۰۰۰ تومان"},
    {"coins": 25,  "toman": 45_000,  "label": "۲۵ سکه — ۴۵٬۰۰۰ تومان"},
    {"coins": 50,  "toman": 80_000,  "label": "۵۰ سکه — ۸۰٬۰۰۰ تومان"},
    {"coins": 100, "toman": 150_000, "label": "۱۰۰ سکه — ۱۵۰٬۰۰۰ تومان"},
]

COINS_PER_REFERRAL = 5

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── State keys (stored in user_data) ────────────────────────────────────────
ST_ANON_MSG    = "sending"
ST_REPLY       = "reply"
ST_BIO         = "bio"
ST_SEARCH      = "search"
ST_LOCATION    = "location"
ST_ADMIN_COIN  = "admin_coin"
ST_RECEIPT     = "receipt"   # waiting for payment receipt photo

# ─── Keyboards ────────────────────────────────────────────────────────────────
def main_menu(user_id: int) -> InlineKeyboardMarkup:
    coins = get_coins(user_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 لینک ناشناس من", callback_data="mylink")],
        [
            InlineKeyboardButton("📍 افراد نزدیک",    callback_data="nearby"),
            InlineKeyboardButton("🔍 جستجو کاربران",  callback_data="search"),
        ],
        [
            InlineKeyboardButton(f"🪙 سکه‌هام: {coins}", callback_data="coins_menu"),
            InlineKeyboardButton("👤 پروفایل",         callback_data="profile"),
        ],
        [InlineKeyboardButton("🎁 معرفی به دوستان (سکه رایگان)", callback_data="refer")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")],
    ])

def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 لینک ناشناس من", callback_data="mylink")],
        [
            InlineKeyboardButton("📍 افراد نزدیک",   callback_data="nearby"),
            InlineKeyboardButton("🔍 جستجو کاربران", callback_data="search"),
        ],
        [
            InlineKeyboardButton("📊 آمار",           callback_data="stats"),
            InlineKeyboardButton("🚫 لیست بلاک",      callback_data="blocklist"),
        ],
        [
            InlineKeyboardButton("🪙 مدیریت سکه",     callback_data="admin_coins"),
            InlineKeyboardButton("💳 پرداخت‌های در انتظار", callback_data="pending_pays"),
        ],
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile")],
        [InlineKeyboardButton("🎁 معرفی به دوستان", callback_data="refer")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")],
    ])

# ─── Helpers ──────────────────────────────────────────────────────────────────
def user_info_text(u) -> str:
    return (
        f"👤 <b>اطلاعات کامل فرستنده</b>\n"
        f"🆔 آیدی عددی: <code>{u.id}</code>\n"
        f"👤 نام: {u.first_name or '—'}\n"
        f"🔖 نام خانوادگی: {u.last_name or '—'}\n"
        f"📛 یوزرنیم: {'@' + u.username if u.username else 'ندارد'}\n"
        f"🌐 زبان: {u.language_code or '—'}\n"
        f"🤖 ربات: {'بله' if u.is_bot else 'خیر'}"
    )

async def send_anon_to_admin(context, sender, msg_type: str, content):
    info    = user_info_text(sender)
    ts      = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    caption = f"📩 <b>پیام ناشناس جدید</b>\n\n{info}\n\n⏰ {ts}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ پاسخ ناشناس", callback_data=f"reply_{sender.id}"),
        InlineKeyboardButton("🚫 بلاک",         callback_data=f"block_{sender.id}"),
    ]])
    if msg_type == "text":
        await context.bot.send_message(
            ADMIN_ID, f"{caption}\n\n💬 <b>پیام:</b>\n{content}",
            parse_mode="HTML", reply_markup=kb
        )
    elif msg_type == "photo":
        await context.bot.send_photo(ADMIN_ID, content, caption=caption, parse_mode="HTML", reply_markup=kb)
    elif msg_type == "video":
        await context.bot.send_video(ADMIN_ID, content, caption=caption, parse_mode="HTML", reply_markup=kb)
    elif msg_type == "voice":
        await context.bot.send_voice(ADMIN_ID, content, caption=caption, parse_mode="HTML", reply_markup=kb)
    elif msg_type == "document":
        await context.bot.send_document(ADMIN_ID, content, caption=caption, parse_mode="HTML", reply_markup=kb)
    elif msg_type == "sticker":
        await context.bot.send_message(ADMIN_ID, caption, parse_mode="HTML", reply_markup=kb)
        await context.bot.send_sticker(ADMIN_ID, content)

def set_state(context, state):
    context.user_data["state"] = state

def get_state(context):
    return context.user_data.get("state")

def clear_state(context):
    context.user_data["state"] = None

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)
    args = context.args or []
    clear_state(context)

    # لینک ناشناس
    if args and args[0] == "send":
        set_state(context, ST_ANON_MSG)
        await update.message.reply_text(
            "🔒 <b>ارسال پیام ناشناس</b>\n\n"
            "پیامت رو بنویس — متن، عکس، ویدیو، ویس یا هر چیزی.\n"
            "هویتت کاملاً مخفی می‌مونه ✉️\n\n"
            "برای لغو /cancel بنویس.",
            parse_mode="HTML"
        )
        return

    # لینک معرفی
    if args and args[0].startswith("ref_"):
        try:
            referrer_id = int(args[0].split("_")[1])
            if referrer_id != user.id:
                if add_referral(referrer_id, user.id):
                    add_coins(referrer_id, COINS_PER_REFERRAL)
                    try:
                        await context.bot.send_message(
                            referrer_id,
                            f"🎉 یه نفر با لینک معرفی تو وارد شد!\n"
                            f"🪙 <b>{COINS_PER_REFERRAL} سکه</b> به حسابت اضافه شد.",
                            parse_mode="HTML"
                        )
                    except:
                        pass
        except:
            pass

    kb = admin_menu() if user.id == ADMIN_ID else main_menu(user.id)
    await update.message.reply_text(
        f"👋 سلام <b>{user.first_name}</b>!\n\nبه ربات پیام ناشناس خوش اومدی 👇",
        parse_mode="HTML", reply_markup=kb
    )

# ─── /cancel ──────────────────────────────────────────────────────────────────
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(context)
    context.user_data.pop("reply_to", None)
    context.user_data.pop("pending_package", None)
    await update.message.reply_text("❌ لغو شد.", reply_markup=ReplyKeyboardRemove())

# ─── Button handler ────────────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user    = query.from_user
    data    = query.data
    await query.answer()

    bot_info = await context.bot.get_me()

    # ── لینک ناشناس
    if data == "mylink":
        link = f"https://t.me/{bot_info.username}?start=send"
        await query.message.reply_text(
            f"🔗 <b>لینک ناشناس تو:</b>\n\n<code>{link}</code>\n\n"
            "این لینک رو برای دوستانت بفرست تا ناشناس برات پیام بذارن.",
            parse_mode="HTML"
        )

    # ── پروفایل
    elif data == "profile":
        u        = get_user(user.id)
        link     = f"https://t.me/{bot_info.username}?start=send"
        ref_cnt  = get_referral_count(user.id)
        bio_text = (u["bio"] or "—") if u else "—"
        text = (
            f"👤 <b>پروفایل شما</b>\n\n"
            f"🏷 نام: {u['first_name']} {u['last_name'] or ''}\n"
            f"📛 یوزرنیم: {'@' + u['username'] if u['username'] else '—'}\n"
            f"📝 بیو: {bio_text}\n"
            f"📩 پیام‌های دریافتی: {u['msg_received']}\n"
            f"📤 پیام‌های فرستاده‌شده: {u['msg_sent']}\n"
            f"🪙 سکه: {u['coins']}\n"
            f"👥 معرفی‌ها: {ref_cnt} نفر\n\n"
            f"🔗 لینک ناشناس:\n<code>{link}</code>"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ ویرایش بیو", callback_data="edit_bio")
        ]])
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)

    # ── ویرایش بیو
    elif data == "edit_bio":
        set_state(context, ST_BIO)
        await query.message.reply_text(
            "✏️ بیوی جدیدت رو بنویس (حداکثر ۱۵۰ کاراکتر):\n\nبرای لغو /cancel بنویس."
        )

    # ── منوی سکه (کاربر)
    elif data == "coins_menu":
        coins = get_coins(user.id)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(pkg["label"], callback_data=f"buy_{i}")]
            for i, pkg in enumerate(COIN_PACKAGES)
        ])
        await query.message.reply_text(
            f"🪙 <b>سکه‌های شما: {coins}</b>\n\n"
            f"برای خرید سکه یکی از پکیج‌های زیر رو انتخاب کن:",
            parse_mode="HTML", reply_markup=kb
        )

    # ── انتخاب پکیج خرید
    elif data.startswith("buy_"):
        idx = int(data.split("_")[1])
        pkg = COIN_PACKAGES[idx]
        context.user_data["pending_package"] = pkg
        set_state(context, ST_RECEIPT)
        await query.message.reply_text(
            f"💳 <b>خرید {pkg['coins']} سکه — {pkg['toman']:,} تومان</b>\n\n"
            f"مبلغ رو به کارت زیر واریز کن:\n\n"
            f"🏦 شماره کارت:\n<code>{CARD_NUMBER}</code>\n"
            f"👤 به نام: <b>{CARD_NAME}</b>\n\n"
            f"بعد از واریز، <b>عکس رسید</b> رو اینجا بفرست.\n\n"
            f"برای لغو /cancel بنویس.",
            parse_mode="HTML"
        )

    # ── معرفی
    elif data == "refer":
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
        ref_cnt  = get_referral_count(user.id)
        await query.message.reply_text(
            f"🎁 <b>معرفی به دوستان</b>\n\n"
            f"به ازای هر نفری که با لینک تو وارد بشه، {COINS_PER_REFERRAL} سکه می‌گیری!\n\n"
            f"👥 معرفی‌های تو: {ref_cnt} نفر\n\n"
            f"🔗 لینک اختصاصی:\n<code>{ref_link}</code>",
            parse_mode="HTML"
        )

    # ── جستجو
    elif data == "search":
        set_state(context, ST_SEARCH)
        await query.message.reply_text(
            "🔍 نام یا یوزرنیم کاربری که دنبالشی رو بنویس:\n\nبرای لغو /cancel بنویس."
        )

    # ── افراد نزدیک
    elif data == "nearby":
        set_state(context, ST_LOCATION)
        loc_btn = KeyboardButton("📍 ارسال موقعیت مکانی", request_location=True)
        kb = ReplyKeyboardMarkup([[loc_btn]], resize_keyboard=True, one_time_keyboard=True)
        await query.message.reply_text(
            "📍 موقعیت مکانیت رو بفرست تا افراد نزدیک رو ببینی:",
            reply_markup=kb
        )

    # ── آمار (ادمین)
    elif data == "stats":
        if user.id != ADMIN_ID:
            return
        s = get_stats()
        await query.message.reply_text(
            f"📊 <b>آمار ربات</b>\n\n"
            f"👥 کل کاربران: <b>{s['total_users']}</b>\n"
            f"📩 کل پیام‌ها: <b>{s['total_msgs']}</b>\n"
            f"📅 پیام‌های امروز: <b>{s['today_msgs']}</b>\n"
            f"🚫 بلاک‌شده: <b>{s['blocked']}</b>\n"
            f"💳 پرداخت در انتظار: <b>{s['pending_pay']}</b>\n"
            f"✅ پرداخت تایید‌شده: <b>{s['confirmed_pay']}</b>",
            parse_mode="HTML"
        )

    # ── لیست بلاک (ادمین)
    elif data == "blocklist":
        if user.id != ADMIN_ID:
            return
        blocked = get_blocked_users()
        if not blocked:
            await query.message.reply_text("✅ هیچ کاربری بلاک نشده.")
        else:
            lines = "\n".join([
                f"• <code>{r['user_id']}</code> — {r['first_name'] or '—'}"
                for r in blocked
            ])
            await query.message.reply_text(f"🚫 <b>بلاک‌شده‌ها:</b>\n\n{lines}", parse_mode="HTML")

    # ── مدیریت سکه (ادمین)
    elif data == "admin_coins":
        if user.id != ADMIN_ID:
            return
        set_state(context, ST_ADMIN_COIN)
        await query.message.reply_text(
            "🪙 <b>مدیریت سکه</b>\n\n"
            "فرمت: <code>آیدی_عددی مقدار</code>\n"
            "دادن ۱۰ سکه: <code>123456789 10</code>\n"
            "گرفتن ۵ سکه: <code>123456789 -5</code>\n\n"
            "برای لغو /cancel بنویس.",
            parse_mode="HTML"
        )

    # ── پرداخت‌های در انتظار (ادمین)
    elif data == "pending_pays":
        if user.id != ADMIN_ID:
            return
        pays = get_pending_payments()
        if not pays:
            await query.message.reply_text("✅ پرداخت در انتظاری وجود نداره.")
            return
        for p in pays:
            u = get_user(p["user_id"])
            name = u["first_name"] if u else "ناشناس"
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ تایید",  callback_data=f"pay_ok_{p['id']}"),
                InlineKeyboardButton("❌ رد",     callback_data=f"pay_no_{p['id']}"),
            ]])
            text = (
                f"💳 <b>درخواست پرداخت #{p['id']}</b>\n\n"
                f"👤 کاربر: {name} (<code>{p['user_id']}</code>)\n"
                f"🪙 سکه: {p['coins']}\n"
                f"💰 مبلغ: {p['amount_toman']:,} تومان\n"
                f"📅 زمان: {p['created_at'][:16]}"
            )
            await query.message.reply_text(text, parse_mode="HTML")
            if p["receipt_file_id"]:
                await context.bot.send_photo(
                    ADMIN_ID, p["receipt_file_id"],
                    caption=f"🧾 رسید پرداخت #{p['id']}",
                    reply_markup=kb
                )

    # ── تایید پرداخت
    elif data.startswith("pay_ok_"):
        if user.id != ADMIN_ID:
            return
        pid = int(data.split("_")[2])
        p   = get_payment(pid)
        if not p or p["status"] != "pending":
            await query.message.reply_text("این پرداخت قبلاً بررسی شده.")
            return
        confirm_payment(pid)
        add_coins(p["user_id"], p["coins"])
        await query.message.reply_text(
            f"✅ پرداخت #{pid} تایید شد.\n🪙 {p['coins']} سکه به کاربر اضافه شد."
        )
        try:
            await context.bot.send_message(
                p["user_id"],
                f"🎉 <b>پرداخت تایید شد!</b>\n\n"
                f"🪙 <b>{p['coins']} سکه</b> به حسابت اضافه شد.\n"
                f"موجودی فعلی: {get_coins(p['user_id'])} سکه",
                parse_mode="HTML"
            )
        except:
            pass

    # ── رد پرداخت
    elif data.startswith("pay_no_"):
        if user.id != ADMIN_ID:
            return
        pid = int(data.split("_")[2])
        p   = get_payment(pid)
        if not p or p["status"] != "pending":
            await query.message.reply_text("این پرداخت قبلاً بررسی شده.")
            return
        reject_payment(pid)
        await query.message.reply_text(f"❌ پرداخت #{pid} رد شد.")
        try:
            await context.bot.send_message(
                p["user_id"],
                "❌ <b>پرداخت رد شد.</b>\n\n"
                "رسید ارسالی تایید نشد. اگه مشکلی داری با ادمین تماس بگیر.",
                parse_mode="HTML"
            )
        except:
            pass

    # ── بلاک کاربر (از پیام ناشناس)
    elif data.startswith("block_"):
        if user.id != ADMIN_ID:
            return
        uid = int(data.split("_")[1])
        set_blocked(uid, True)
        await query.message.reply_text(f"🚫 کاربر <code>{uid}</code> بلاک شد.", parse_mode="HTML")

    # ── پاسخ ناشناس
    elif data.startswith("reply_"):
        if user.id != ADMIN_ID:
            return
        uid = int(data.split("_")[1])
        context.user_data["reply_to"] = uid
        set_state(context, ST_REPLY)
        await query.message.reply_text(
            f"✏️ پیام پاسخت رو بنویس (ناشناس به کاربر <code>{uid}</code>):\n\n"
            "برای لغو /cancel بنویس.",
            parse_mode="HTML"
        )

    # ── راهنما
    elif data == "help":
        await query.message.reply_text(
            "❓ <b>راهنما</b>\n\n"
            "🔗 <b>لینک ناشناس:</b> لینکت رو بگیر و برای دوستانت بفرست تا ناشناس پیام بدن.\n\n"
            "📍 <b>افراد نزدیک:</b> موقعیتت رو بفرست و ببین کی در اطرافته.\n\n"
            "🔍 <b>جستجو:</b> با اسم یا یوزرنیم کاربر پیداش کن.\n\n"
            "🪙 <b>سکه:</b> با خرید یا معرفی دوستان سکه جمع کن.\n\n"
            "👤 <b>پروفایل:</b> اطلاعاتت رو ببین و بیو بنویس.\n\n"
            "🎁 <b>معرفی:</b> هر معرفی = ۵ سکه رایگان.",
            parse_mode="HTML"
        )

# ─── Message router ────────────────────────────────────────────────────────────
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    message = update.message
    state   = get_state(context)

    upsert_user(user)

    # ── پیام ناشناس
    if state == ST_ANON_MSG:
        if user.id == ADMIN_ID:
            await message.reply_text("از پنل ادمین یا دکمه‌های پاسخ استفاده کن.")
            clear_state(context)
            return
        if is_blocked(user.id):
            await message.reply_text("⛔️ شما مسدود شده‌اید.")
            clear_state(context)
            return
        try:
            if message.text:
                await send_anon_to_admin(context, user, "text", message.text)
            elif message.photo:
                await send_anon_to_admin(context, user, "photo", message.photo[-1].file_id)
            elif message.video:
                await send_anon_to_admin(context, user, "video", message.video.file_id)
            elif message.voice:
                await send_anon_to_admin(context, user, "voice", message.voice.file_id)
            elif message.document:
                await send_anon_to_admin(context, user, "document", message.document.file_id)
            elif message.sticker:
                await send_anon_to_admin(context, user, "sticker", message.sticker.file_id)
            else:
                await message.reply_text("این نوع پیام پشتیبانی نمی‌شه.")
                return
            log_message(user.id, ADMIN_ID)
            await message.reply_text("✅ پیامت ناشناس فرستاده شد!")
        except Exception as e:
            logger.error(e)
            await message.reply_text("❌ خطا. دوباره امتحان کن.")
        clear_state(context)

    # ── پاسخ ادمین
    elif state == ST_REPLY and user.id == ADMIN_ID:
        reply_to = context.user_data.get("reply_to")
        if reply_to:
            try:
                if message.text:
                    await context.bot.send_message(
                        reply_to,
                        f"💬 <b>پاسخ ناشناس دریافت کردی:</b>\n\n{message.text}",
                        parse_mode="HTML"
                    )
                elif message.photo:
                    await context.bot.send_photo(reply_to, message.photo[-1].file_id, caption="📷 پاسخ ناشناس")
                elif message.video:
                    await context.bot.send_video(reply_to, message.video.file_id, caption="🎥 پاسخ ناشناس")
                elif message.voice:
                    await context.bot.send_voice(reply_to, message.voice.file_id)
                elif message.document:
                    await context.bot.send_document(reply_to, message.document.file_id, caption="📎 پاسخ ناشناس")
                await message.reply_text("✅ پاسخ ناشناس فرستاده شد.")
            except Exception as e:
                await message.reply_text(f"❌ خطا: {e}")
        context.user_data.pop("reply_to", None)
        clear_state(context)

    # ── بیو
    elif state == ST_BIO:
        bio = message.text[:150] if message.text else ""
        update_bio(user.id, bio)
        await message.reply_text(f"✅ بیوت ذخیره شد:\n<i>{bio}</i>", parse_mode="HTML")
        clear_state(context)

    # ── جستجو
    elif state == ST_SEARCH:
        query_text = message.text.strip() if message.text else ""
        results    = search_users(query_text)
        if not results:
            await message.reply_text("❌ کاربری پیدا نشد.")
        else:
            bot_info = await context.bot.get_me()
            text = f"🔍 <b>نتایج برای «{query_text}»:</b>\n\n"
            for r in results[:10]:
                name  = r["first_name"] or "بی‌نام"
                uname = f"@{r['username']}" if r["username"] else "—"
                link  = f"https://t.me/{bot_info.username}?start=send"
                text += f"👤 <b>{name}</b> ({uname})\n📩 {r['msg_received']} پیام دریافتی\n🔗 <a href='{link}'>پیام ناشناس</a>\n\n"
            await message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
        clear_state(context)

    # ── مدیریت سکه ادمین
    elif state == ST_ADMIN_COIN and user.id == ADMIN_ID:
        try:
            parts   = message.text.strip().split()
            uid     = int(parts[0])
            amount  = int(parts[1])
            add_coins(uid, amount)
            action  = "اضافه" if amount > 0 else "کم"
            await message.reply_text(
                f"✅ {abs(amount)} سکه به کاربر <code>{uid}</code> {action} شد.\n"
                f"💰 موجودی جدید: {get_coins(uid)} سکه",
                parse_mode="HTML"
            )
        except:
            await message.reply_text(
                "❌ فرمت اشتباه.\nمثال: <code>123456789 10</code>",
                parse_mode="HTML"
            )
        clear_state(context)

    # ── رسید پرداخت
    elif state == ST_RECEIPT:
        pkg = context.user_data.get("pending_package")
        if not pkg:
            clear_state(context)
            return
        if not message.photo:
            await message.reply_text("⚠️ لطفاً عکس رسید رو بفرست.")
            return
        file_id = message.photo[-1].file_id
        pid     = create_payment(user.id, pkg["toman"], pkg["coins"], file_id)
        # اطلاع به ادمین
        u = get_user(user.id)
        name = u["first_name"] if u else "ناشناس"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ تایید", callback_data=f"pay_ok_{pid}"),
            InlineKeyboardButton("❌ رد",    callback_data=f"pay_no_{pid}"),
        ]])
        try:
            await context.bot.send_photo(
                ADMIN_ID, file_id,
                caption=(
                    f"💳 <b>درخواست پرداخت جدید #{pid}</b>\n\n"
                    f"👤 {name} (<code>{user.id}</code>)\n"
                    f"🪙 {pkg['coins']} سکه\n"
                    f"💰 {pkg['toman']:,} تومان"
                ),
                parse_mode="HTML", reply_markup=kb
            )
        except Exception as e:
            logger.error(e)
        await message.reply_text(
            "✅ <b>رسیدت دریافت شد!</b>\n\n"
            "بعد از تایید ادمین، سکه‌ها به حسابت اضافه می‌شن.\n"
            "معمولاً کمتر از ۳۰ دقیقه طول می‌کشه.",
            parse_mode="HTML"
        )
        context.user_data.pop("pending_package", None)
        clear_state(context)

    # ── پیش‌فرض
    else:
        kb = admin_menu() if user.id == ADMIN_ID else main_menu(user.id)
        await message.reply_text("از منوی زیر استفاده کن 👇", reply_markup=kb)

# ─── Location ──────────────────────────────────────────────────────────────────
async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    state = get_state(context)
    if state != ST_LOCATION:
        return
    loc = update.message.location
    update_location(user.id, loc.latitude, loc.longitude)
    nearby   = get_nearby_users(loc.latitude, loc.longitude)
    bot_info = await context.bot.get_me()
    text     = "📍 <b>افراد نزدیک به شما:</b>\n\n"
    found    = False
    for dist, r in nearby:
        if r["user_id"] == user.id:
            continue
        name  = r["first_name"] or "بی‌نام"
        uname = f"@{r['username']}" if r["username"] else "—"
        link  = f"https://t.me/{bot_info.username}?start=send"
        text += f"👤 <b>{name}</b> ({uname})\n📏 ~{dist:.0f} کیلومتر\n🔗 <a href='{link}'>پیام ناشناس</a>\n\n"
        found = True
    if not found:
        text = "😕 در شعاع ۵۰ کیلومتری کاربری پیدا نشد."
    await update.message.reply_text(
        text, parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
        disable_web_page_preview=True
    )
    clear_state(context)

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(~filters.COMMAND, message_router))

    logger.info("✅ Bot v3 started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
