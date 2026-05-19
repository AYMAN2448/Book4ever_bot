import asyncio
import aiosqlite
import requests
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
import os

# ============ الإعدادات ============
BOT_TOKEN = "8840922039:AAEXrfY4b3KgU-dqNxAYuOc7-2Agkvenw-4"
ADMIN_ID = 8585868701

# 1. التحويل البنكي - Kashy
BANK_INFO = """
🏦 **التحويل عبر كاشي**
الاسم: لبني احمد سعيد
رقم الحساب: 401951393
"""

# 2. TRX
TRX_ADDRESS = "TArc3MovymaBrNmR4e4iRidLFx15BbDQ5L"
TRX_RATE_USD = 0.15 # غيّر السعر حسب السوق

# 3. USDT TRC-20
USDT_ADDRESS = "0x1b90069d9503e1931d30a8884080cdf16bd0cded"
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", ":be37dba7-d9a7-4020-a8dc-389c143df032")
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t" # عقد USDT الرسمي على Tron

# 4. Binance Pay
BINANCE_PAY_LINK = os.getenv("BINANCE_PAY_LINK","https://s.binance.com/UmsqRNki")

DB_PATH = "books.db"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

class BuyStates(StatesGroup):
    waiting_proof = State()

# ============ قاعدة البيانات ============
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY,
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

# ============ القائمة الرئيسية ============
@router.message(CommandStart())
async def start(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        books = await db.execute_fetchall("SELECT id, title, author, price_usd FROM books")

    if not books:
        await message.answer("لا يوجد كتب حالياً")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{b[1]} - {b[2]} | ${b[3]}", callback_data=f"book_{b[0]}")]
        for b in books
    ])
    await message.answer("📚 أهلاً بك في **book 4ever**\nاختر الكتاب:", parse_mode="Markdown", reply_markup=kb)

# ============ اختيار طريقة الدفع ============
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

# ============ 1. التحويل البنكي - يدوي ============
@router.callback_query(F.data == "pay_bank")
async def pay_bank(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        BANK_INFO + "\nبعد التحويل أرسل صورة إيصال الدفع هنا.",
        parse_mode="Markdown"
    )
    await state.set_state(BuyStates.waiting_proof)

@router.message(BuyStates.waiting_proof, F.photo)
async def receive_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, book_id, method, proof_msg_id) VALUES (?,?, 'bank',?)",
            (message.from_user.id, book_id, message.message_id)
        )
        order_id = cursor.lastrowid
        await db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ موافقة", callback_data=f"approve_{order_id}")],
        [InlineKeyboardButton(text="❌ رفض", callback_data=f"reject_{order_id}")]
    ])
    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await bot.send_message(ADMIN_ID, f"طلب جديد # {order_id}\nالمستخدم: @{message.from_user.username}", reply_markup=kb)

    await message.answer("✅ تم استلام الإيصال. سيتم التحقق خلال 24 ساعة.")
    await state.clear()

@router.callback_query(F.data.startswith("approve_"))
async def approve_order(call: CallbackQuery):
    order_id = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id, book_id FROM orders WHERE id=? AND status='pending'", (order_id,))
order = await cursor.fetchone()
        if not order:
            await call.answer("الطلب غير موجود")
            return
        await db.execute("UPDATE orders SET status='paid' WHERE id=?", (order_id,))
        await db.commit()

    async with aiosqlite.connect(DB_PATH) as db:
       cursor = await db.execute("SELECT file_path FROM books WHERE id=?", (book_id,))
book = await cursor.fetchone()

    await bot.send_document(order[0], FSInputFile(book[0]), caption=f"✅ تم تأكيد الدفع!\nكتابك: {book[1]}")
    await call.message.edit_text("تمت الموافقة وإرسال الكتاب.")

@router.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    order_id = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status='rejected' WHERE id=?", (order_id,))
        cursor = await db.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
order = await cursor.fetchone()
        await db.commit()
    await bot.send_message(order[0], "❌ تم رفض إثبات الدفع. تواصل مع الأدمن.")
    await call.message.edit_text("تم الرفض.")

# ============ 2. TRX - تحقق تلقائي ============
@router.callback_query(F.data == "pay_trx")
async def pay_trx(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']

    async with aiosqlite.connect(DB_PATH) as db:
      cursor = await db.execute("SELECT price FROM books WHERE id=?", (book_id,))
book = await cursor.fetchone()
        
    amount_trx = round(book[0] / TRX_RATE_USD, 2)

    await call.message.edit_text(
        f"🪙 **الدفع بـ TRX**\n\n"
        f"أرسل **{amount_trx} TRX** إلى:\n`{TRX_ADDRESS}`\n\n"
        f"المبلغ يعادل ${book[0]}\n"
        f"مهم: اكتب `{call.from_user.id}` في خانة Memo/Note\n"
        f"بعد الإرسال اضغط 'تحققت'.\n"
        f"⚠️ أرسل على شبكة **TRON** فقط",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 تحققت من الدفع", callback_data=f"check_trx_{book_id}")]
        ])
    )

@router.callback_query(F.data.startswith("check_trx_"))
async def check_trx(call: CallbackQuery):
    book_id = int(call.data.split("_")[1])
    user_id = call.from_user.id

    url = f"https://api.trongrid.io/v1/accounts/{TRX_ADDRESS}/transactions?limit=10&sort=-timestamp"
    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}

    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        for tx in res.get('data', []):
            if tx.get('to') == TRX_ADDRESS.lower() and tx.get('contract_type') == 'TransferContract':
                memo = tx.get('data', '')
                if str(user_id) in memo:
                    async with aiosqlite.connect(DB_PATH) as db:
                        book = await db.execute_fetchone("SELECT file_path, title FROM books WHERE id=?", (book_id,))
                        await db.execute("INSERT INTO orders (user_id, book_id, method, status) VALUES (?,?, 'trx', 'paid')",
                                         (user_id, book_id))
                        await db.commit()
                    await bot.send_document(user_id, FSInputFile(book[0]), caption=f"✅ تم الدفع بـ TRX!\nكتابك: {book[1]}")
                    await call.message.edit_text("تم تأكيد الدفع وإرسال الكتاب.")
                    return
    except Exception as e:
        print("TRX Error:", e)

    await call.answer("لم يتم العثور على الدفع. تأكد من المبلغ والميمو وانتظر 1-2 دقيقة.")

# ============ 3. USDT TRC-20 - تحقق تلقائي ============
@router.callback_query(F.data == "pay_usdt")
async def pay_usdt(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']

    async with aiosqlite.connect(DB_PATH) as db:
        book = await db.execute_fetchone("SELECT price_usd, title FROM books WHERE id=?", (book_id,))

    amount = book[0]

    await call.message.edit_text(
        f"💵 **الدفع بـ USDT على شبكة Tron TRC-20**\n\n"
        f"أرسل **{amount} USDT** إلى:\n`{USDT_ADDRESS}`\n\n"
        f"⚠️ استخدم شبكة **TRC-20** فقط. الحد الأدنى 5 USDT شغال.\n"
        f"بعد الإرسال اضغط 'تحققت'.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 تحققت من الدفع", callback_data=f"check_usdt_{book_id}")]
        ])
    )

@router.callback_query(F.data.startswith("check_usdt_"))
async def check_usdt(call: CallbackQuery):
    book_id = int(call.data.split("_")[1])
    user_id = call.from_user.id

    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}
    url = f"https://api.trongrid.io/v1/accounts/{USDT_ADDRESS}/transactions/trc20?limit=20&contract_address={USDT_CONTRACT}"

    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        for tx in res.get('data', []):
            if tx.get('to') == USDT_ADDRESS.lower() and tx.get('token_info', {}).get('address') == USDT_CONTRACT:
                value = int(tx['value']) / 1_000_000
                if value >= book[0] and tx.get('transaction_info', {}).get('receipt', {}).get('result') == 'SUCCESS':
                    async with aiosqlite.connect(DB_PATH) as db:
                        book = await db.execute_fetchone("SELECT file_path, title FROM books WHERE id=?", (book_id,))
                        await db.execute("INSERT INTO orders (user_id, book_id, method, status) VALUES (?,?, 'usdt', 'paid')",
                                         (user_id, book_id))
                        await db.commit()
                    await bot.send_document(user_id, FSInputFile(book[0]), caption=f"✅ تم الدفع بـ USDT!\nكتابك: {book[1]}")
                    await call.message.edit_text("تم تأكيد الدفع وإرسال الكتاب.")
                    return
    except Exception as e:
        print("USDT Error:", e)

    await call.answer("لم يتم العثور على الدفع. تأكد إنك حولت على TRC-20 وانتظرت 1-2 دقيقة.")

# ============ 4. Binance Pay ============
@router.callback_query(F.data == "pay_binance")
async def pay_binance(call: CallbackQuery):
    await call.message.edit_text(
        f"🟡 **Binance Pay**\n\n"
        f"ادفع من هنا:\n{BINANCE_PAY_LINK}\n"
        f"بعد الدفع راسل الأدمن لتأكيد الطلب يدوياً.",
        parse_mode="Markdown"
    )

# ============ أوامر الأدمن ============
@router.message(Command("addbook"))
async def add_book_cmd(message: Message):
    if message.from_user.id!= ADMIN_ID:
        return
    await message.answer("أرسل بصيغة:\nالعنوان | المؤلف | السعر | مسار_الملف\nمثال:\nالارض | نجيب محفوظ | 5 | books/book.pdf")

@router.message(F.text.contains("|"))
async def save_book(message: Message):
    if message.from_user.id!= ADMIN_ID:
        return
    try:
        title, author, price, path = [x.strip() for x in message.text.split("|")]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO books (title, author, price_usd, file_path) VALUES (?,?,?,?)",
                             (title, author, float(price), path))
            await db.commit()
        await message.answer("✅ تم إضافة الكتاب")
    except Exception as e:
        await message.answer(f"خطأ: {e}")

@router.message(Command("panel"))
async def admin_panel(message: Message):
    if message.from_user.id!= ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        pending = await db.execute_fetchall("SELECT id, user_id, book_id, method FROM orders WHERE status='pending'")
    if not pending:
        await message.answer("لا يوجد طلبات معلقة")
        return
    text = "\n".join([f"طلب #{p[0]} | مستخدم {p[1]} | كتاب {p[2]} | {p[3]}" for p in pending])
    await message.answer(f"الطلبات المعلقة:\n{text}")

async def main():
    await init_db()
    print("Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
