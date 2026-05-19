import asyncio
import aiosqlite
import requests
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ============ قراءة المتغيرات من البيئة (مع قيم افتراضية) ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "8840922039:AAEXrfY4b3KgU-dqNxAYuOc7-2Agkvenw-4")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8585868701"))

BANK_INFO = os.getenv("BANK_INFO", "🏦 التحويل عبر كاشي\nالاسم: لبني احمد سعيد\nرقم الحساب: 401951393")
TRX_ADDRESS = os.getenv("TRX_ADDRESS", "TArc3MovymaBrNmR4e4iRidLFx15BbDQ5L")
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "0x1b90069d9503e1931d30a8884080cdf16bd0cded")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "be37dba7-d9a7-4020-a8dc-389c143df032")
USDT_CONTRACT = os.getenv("USDT_CONTRACT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
BINANCE_PAY_LINK = os.getenv("BINANCE_PAY_LINK", "https://s.binance.com/UmsqRNki")
TRX_RATE_USD = float(os.getenv("TRX_RATE_USD", "0.15"))

DB_PATH = "books.db"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ============ تعريف الحالات (States) ============
class BuyStates(StatesGroup):
    waiting_proof = State()

class BroadcastStates(StatesGroup):
    waiting_message = State()

class AddBookState(StatesGroup):
    waiting_details = State()

# ============ قاعدة البيانات ============
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author TEXT,
            price_usd REAL,
            file_path TEXT
        )""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            book_id INTEGER,
            method TEXT,
            status TEXT DEFAULT 'pending',
            proof_msg_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        await db.commit()

async def get_book_by_id(book_id):
    async with aiosqlite.connect(DB_PATH) as db:
        return await db.execute_fetchone("SELECT title, author, price_usd, file_path FROM books WHERE id=?", (book_id,))

async def count_sold_books():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM orders WHERE status='paid'")
        count = await cursor.fetchone()
        return count[0] if count else 0

async def total_revenue():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT SUM(price_usd) FROM books WHERE id IN (SELECT book_id FROM orders WHERE status='paid')")
        total = await cursor.fetchone()
        return total[0] if total[0] else 0.0

# ============ الأوامر (نفس الكود السابق كاملاً) ============
@router.message(CommandStart())
async def start(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        books = await db.execute_fetchall("SELECT id, title, author, price_usd FROM books")
    if not books:
        await message.answer("📚 لا يوجد كتب حالياً.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{b[1]} - {b[2]} | ${b[3]}", callback_data=f"book_{b[0]}")]
        for b in books
    ])
    await message.answer("📚 أهلاً بك في **book 4ever**\nاختر الكتاب:", parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data.startswith("book_"))
async def choose_payment(call: CallbackQuery, state: FSMContext):
    book_id = int(call.data.split("_")[1])
    await state.update_data(book_id=book_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏦 تحويل بنكي - كاشي", callback_data="pay_bank")],
        [InlineKeyboardButton(text="🪙 TRX", callback_data="pay_trx")],
        [InlineKeyboardButton(text="💵 USDT TRC-20", callback_data="pay_usdt")],
        [InlineKeyboardButton(text="🟡 Binance Pay", callback_data="pay_binance")]
    ])
    await call.message.edit_text("اختر طريقة الدفع:", reply_markup=kb)

@router.callback_query(F.data == "pay_bank")
async def pay_bank(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(BANK_INFO + "\n\n📎 بعد التحويل أرسل صورة إيصال الدفع هنا.", parse_mode="Markdown")
    await state.set_state(BuyStates.waiting_proof)

@router.message(BuyStates.waiting_proof, F.photo)
async def receive_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, book_id, method, proof_msg_id, status) VALUES (?,?, 'bank',?, 'pending')",
            (message.from_user.id, book_id, message.message_id)
        )
        order_id = cursor.lastrowid
        await db.commit()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ موافقة", callback_data=f"approve_{order_id}")],
        [InlineKeyboardButton(text="❌ رفض", callback_data=f"reject_{order_id}")]
    ])
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await bot.send_message(ADMIN_ID, f"📦 طلب جديد #{order_id}\n👤 @{message.from_user.username}\n📖 كتاب ID: {book_id}", reply_markup=kb)
    await message.answer("✅ تم استلام الإيصال. سيتم التحقق خلال 24 ساعة.")
    await state.clear()

@router.callback_query(F.data.startswith("approve_"))
async def approve_order(call: CallbackQuery):
    order_id = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        order = await db.execute_fetchone("SELECT user_id, book_id FROM orders WHERE id=? AND status='pending'", (order_id,))
        if not order:
            await call.answer("الطلب غير موجود أو تم معالجته")
            return
        await db.execute("UPDATE orders SET status='paid' WHERE id=?", (order_id,))
        await db.commit()
    book = await get_book_by_id(order[1])
    if not book or not os.path.exists(book[3]):
        await bot.send_message(order[0], "⚠️ عذراً، ملف الكتاب غير موجود. تواصل مع الأدمن.")
        await call.message.edit_text("⚠️ فشل الإرسال: الملف غير موجود.")
        return
    await bot.send_document(order[0], FSInputFile(book[3]), caption=f"✅ تم تأكيد الدفع!\n📖 {book[0]} - {book[1]}")
    await call.message.edit_text("✅ تمت الموافقة وإرسال الكتاب.")

@router.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    order_id = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status='rejected' WHERE id=?", (order_id,))
        order = await db.execute_fetchone("SELECT user_id FROM orders WHERE id=?", (order_id,))
        await db.commit()
    if order:
        await bot.send_message(order[0], "❌ تم رفض إثبات الدفع. تواصل مع الأدمن.")
    await call.message.edit_text("❌ تم رفض الطلب.")

@router.callback_query(F.data == "pay_trx")
async def pay_trx(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']
    book = await get_book_by_id(book_id)
    if not book:
        await call.answer("الكتاب غير موجود")
        return
    amount_trx = round(book[2] / TRX_RATE_USD, 2)
    await call.message.edit_text(
        f"🪙 **الدفع بـ TRX**\n\nأرسل **{amount_trx} TRX** إلى:\n`{TRX_ADDRESS}`\n\nالمبلغ يعادل ${book[2]}\n**هام:** اكتب `{call.from_user.id}` في خانة Memo.\nبعد الإرسال اضغط 'تحققت'.\n⚠️ شبكة TRON فقط.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 تحققت من الدفع", callback_data=f"check_trx_{book_id}")]
        ])
    )

@router.callback_query(F.data.startswith("check_trx_"))
async def check_trx(call: CallbackQuery):
    book_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    url = f"https://api.trongrid.io/v1/accounts/{TRX_ADDRESS}/transactions?limit=15&sort=-timestamp"
    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        for tx in res.get('data', []):
            if tx.get('to') == TRX_ADDRESS.lower() and tx.get('contract_type') == 'TransferContract':
                memo = tx.get('data', '')
                if str(user_id) in memo:
                    book = await get_book_by_id(book_id)
                    if not book:
                        await call.answer("خطأ")
                        return
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("INSERT INTO orders (user_id, book_id, method, status) VALUES (?,?, 'trx', 'paid')", (user_id, book_id))
                        await db.commit()
                    if os.path.exists(book[3]):
                        await bot.send_document(user_id, FSInputFile(book[3]), caption=f"✅ تم الدفع بـ TRX!\n📖 {book[0]}")
                        await call.message.edit_text("✅ تم تأكيد الدفع وإرسال الكتاب.")
                    else:
                        await bot.send_message(user_id, "⚠️ تم الدفع لكن الملف غير موجود.")
                    return
    except Exception as e:
        print("TRX error:", e)
    await call.answer("لم يتم العثور على الدفع. تأكد من المبلغ والميمو.", show_alert=True)

@router.callback_query(F.data == "pay_usdt")
async def pay_usdt(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']
    book = await get_book_by_id(book_id)
    if not book:
        await call.answer("الكتاب غير موجود")
        return
    await call.message.edit_text(
        f"💵 **الدفع بـ USDT (TRC-20)**\n\nأرسل **${book[2]} USDT** إلى:\n`{USDT_ADDRESS}`\n\n⚠️ شبكة TRC-20 فقط.\nبعد الإرسال اضغط 'تحققت'.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 تحققت من الدفع", callback_data=f"check_usdt_{book_id}")]
        ])
    )

@router.callback_query(F.data.startswith("check_usdt_"))
async def check_usdt(call: CallbackQuery):
    book_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    book = await get_book_by_id(book_id)
    if not book:
        await call.answer("خطأ")
        return
    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY} if TRONGRID_API_KEY else {}
    url = f"https://api.trongrid.io/v1/accounts/{USDT_ADDRESS}/transactions/trc20?limit=20&contract_address={USDT_CONTRACT}"
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        for tx in res.get('data', []):
            if tx.get('to') == USDT_ADDRESS.lower():
                value = int(tx['value']) / 1_000_000
                if value >= book[2]:
                    async with aiosqlite.connect(DB_PATH) as db:
                        existing = await db.execute_fetchone("SELECT id FROM orders WHERE user_id=? AND book_id=? AND status='paid'", (user_id, book_id))
                        if not existing:
                            await db.execute("INSERT INTO orders (user_id, book_id, method, status) VALUES (?,?, 'usdt', 'paid')", (user_id, book_id))
                            await db.commit()
                    if os.path.exists(book[3]):
                        await bot.send_document(user_id, FSInputFile(book[3]), caption=f"✅ تم الدفع بـ USDT!\n📖 {book[0]}")
                        await call.message.edit_text("✅ تم تأكيد الدفع وإرسال الكتاب.")
                    else:
                        await bot.send_message(user_id, "⚠️ تم الدفع لكن الملف غير موجود.")
                    return
    except Exception as e:
        print("USDT error:", e)
    await call.answer("لم يتم العثور على الدفع.", show_alert=True)

@router.callback_query(F.data == "pay_binance")
async def pay_binance(call: CallbackQuery):
    await call.message.edit_text(f"🟡 **Binance Pay**\n\nادفع من هنا:\n{BINANCE_PAY_LINK}\n\nبعد الدفع راسل الأدمن.")

# ============ أوامر الأدمن ============
@router.message(Command("addbook"))
async def addbook_instruction(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "📚 **إضافة كتاب جديد**\n\n"
        "أرسل ملف PDF مع كابشن بهذا الشكل:\n"
        "`العنوان | المؤلف | السعر`\n\n"
        "مثال:\n"
        "`الأرض | نجيب محفوظ | 5`\n\n"
        "سيتم حفظ الملف تلقائياً وإضافة الكتاب.",
        parse_mode="Markdown"
    )

@router.message(F.document)
async def add_book_from_pdf(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    if not message.document.file_name.endswith('.pdf'):
        await message.answer("⚠️ يرجى إرسال ملف PDF فقط.")
        return
    if not message.caption:
        await message.answer("⚠️ يرجى إضافة كابشن بالصيغة: `العنوان | المؤلف | السعر`", parse_mode="Markdown")
        return
    parts = [p.strip() for p in message.caption.split("|")]
    if len(parts) != 3:
        await message.answer("⚠️ الصيغة غير صحيحة. استخدم: `العنوان | المؤلف | السعر`", parse_mode="Markdown")
        return
    title, author, price_str = parts
    try:
        price = float(price_str)
    except:
        await message.answer("⚠️ السعر يجب أن يكون رقماً (مثال: 5 أو 5.99)")
        return
    file_name = f"{title}_{author}.pdf".replace(" ", "_").replace("/", "_")
    file_path = f"books/{file_name}"
    os.makedirs("books", exist_ok=True)
    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, file_path)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO books (title, author, price_usd, file_path) VALUES (?,?,?,?)",
            (title, author, price, file_path)
        )
        await db.commit()
    await message.answer(f"✅ تم إضافة الكتاب **{title}** للمؤلف **{author}** بسعر ${price}\n📁 المسار: `{file_path}`", parse_mode="Markdown")

@router.message(Command("addbook2"))
async def addbook2(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("أرسل تفاصيل الكتاب:\nالعنوان\nالمؤلف\nالسعر\nالمسار (مثال: books/file.pdf)")
    await state.set_state(AddBookState.waiting_details)

@router.message(AddBookState.waiting_details)
async def process_addbook(message: Message, state: FSMContext):
    lines = message.text.strip().split("\n")
    if len(lines) < 4:
        await message.answer("أرسل 4 أسطر: العنوان، المؤلف، السعر، المسار")
        return
    title, author, price_str, path = lines[0].strip(), lines[1].strip(), lines[2].strip(), lines[3].strip()
    try:
        price = float(price_str)
        if not os.path.exists(path):
            await message.answer(f"⚠️ الملف غير موجود: {path}")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO books (title, author, price_usd, file_path) VALUES (?,?,?,?)", (title, author, price, path))
            await db.commit()
        await message.answer(f"✅ تم إضافة الكتاب **{title}**")
    except Exception as e:
        await message.answer(f"خطأ: {e}")
    await state.clear()

@router.message(Command("stats"))
async def stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("للمشرف فقط.")
        return
    sold = await count_sold_books()
    revenue = await total_revenue()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM orders WHERE status='pending'")
        pending = (await cursor.fetchone())[0]
    await message.answer(f"📊 **الإحصائيات**\n📚 مباع: {sold}\n💰 الأرباح: ${revenue}\n⏳ معلقة: {pending}", parse_mode="Markdown")

@router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("أرسل الرسالة (نص، صورة، ملف) ليتم نشرها لجميع المستخدمين.")
    await state.set_state(BroadcastStates.waiting_message)

@router.message(BroadcastStates.waiting_message, F.text | F.photo | F.document)
async def send_broadcast(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        users = await db.execute_fetchall("SELECT DISTINCT user_id FROM orders")
    if not users:
        await message.answer("لا يوجد مستخدمون.")
        await state.clear()
        return
    success = 0
    for (user_id,) in users:
        try:
            if message.text:
                await bot.send_message(user_id, message.text)
            elif message.photo:
                await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption)
            elif message.document:
                await bot.send_document(user_id, message.document.file_id, caption=message.caption)
            success += 1
        except:
            pass
    await message.answer(f"📢 تم الإرسال إلى {success} مستخدم.")
    await state.clear()

@router.message(Command("panel"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_PATH) as db:
        pending = await db.execute_fetchall("SELECT id, user_id, book_id, method FROM orders WHERE status='pending'")
    if not pending:
        await message.answer("✅ لا توجد طلبات معلقة.")
        return
    text = "\n".join([f"طلب #{p[0]} | مستخدم {p[1]} | كتاب {p[2]} | {p[3]}" for p in pending])
    await message.answer(f"**الطلبات المعلقة:**\n{text}", parse_mode="Markdown")

@router.message(Command("delbook"))
async def delbook(message: Message):
    if message.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_PATH) as db:
        books = await db.execute_fetchall("SELECT id, title FROM books")
    if not books:
        await message.answer("لا توجد كتب.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b[1], callback_data=f"delbook_{b[0]}")] for b in books
    ])
    await message.answer("اختر الكتاب لحذفه:", reply_markup=kb)

@router.callback_query(F.data.startswith("delbook_"))
async def confirm_delbook(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("غير مصرح")
        return
    book_id = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM books WHERE id=?", (book_id,))
        await db.commit()
    await call.message.edit_text("✅ تم حذف الكتاب.")

# ============ تشغيل البوت باستخدام Polling (بدون Flask) ============
async def main():
    await init_db()
    print("Bot started polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
