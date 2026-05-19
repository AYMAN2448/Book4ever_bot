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

BANK_INFO = """
🏦 **التحويل عبر كاشي**
الاسم: لبني احمد سعيد
رقم الحساب: 401951393
"""

TRX_ADDRESS = "TArc3MovymaBrNmR4e4iRidLFx15BbDQ5L"
TRX_RATE_USD = 0.15

USDT_ADDRESS = "0x1b90069d9503e1931d30a8884080cdf16bd0cded"
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "be37dba7-d9a7-4020-a8dc-389c143df032")
USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

BINANCE_PAY_LINK = os.getenv("BINANCE_PAY_LINK","https://s.binance.com/UmsqRNki")
DB_PATH = "books.db"

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

class BuyStates(StatesGroup):
    waiting_proof = State()
    waiting_broadcast = State()

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
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )""")
        await db.commit()

# ============ القائمة الرئيسية ============
@router.message(CommandStart())
async def start(message: Message):
    # حفظ المستخدم للإشعارات
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, title, author, price_usd FROM books")
        books = await cursor.fetchall()

    kb_buttons = [[InlineKeyboardButton(text=f"{b[1]} - {b[2]} | ${b[3]}", callback_data=f"book_{b[0]}")] for b in books]

    if message.from_user.id == ADMIN_ID:
        kb_buttons.append([InlineKeyboardButton(text="📢 إرسال إشعار", callback_data="broadcast")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    await message.answer("📚 أهلاً بك في **book 4ever**\nاختر الكتاب:", parse_mode="Markdown", reply_markup=kb)

# ============ إرسال إشعار للمشتركين - للأدمن فقط ============
@router.callback_query(F.data == "broadcast")
async def ask_broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id!= ADMIN_ID:
        return
    await call.message.answer("أرسل الرسالة التي تريد إرسالها لجميع المشتركين:")
    await state.set_state(BuyStates.waiting_broadcast)

@router.message(BuyStates.waiting_broadcast)
async def do_broadcast(message: Message, state: FSMContext):
    if message.from_user.id!= ADMIN_ID:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users")
        users = await cursor.fetchall()

    success = 0
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 **إشعار من الإدارة:**\n\n{message.text}", parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05) # تجنب limit التلغرام
        except:
            pass

    await message.answer(f"✅ تم إرسال الإشعار لـ {success} مشترك")
    await state.clear()

# 👇 ضيف ده هنا
@router.message(Command("addbook"))
async def add_book(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("ما عندك صلاحية.")
        return
    
    try:
        _, data = message.text.split(" ", 1)
        book_id, title, author, price, file_path = data.split("|")
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO books VALUES (?,?,?,?,?)",
                (int(book_id), title, author, float(price), file_path)
            )
            await db.commit()
        
        await message.answer(f"✅ تم إضافة الكتاب: {title}")
        
    except Exception as e:
        await message.answer(f"خطأ: {e}")

# ================== اختيار طريقة الدفع ==================
@router.callback_query(F.data.startswith("pay_"))
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
    await state.update_data(method="bank")

@router.callback_query(F.data == "pay_trx")
async def pay_trx(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT price_usd FROM books WHERE id=?", (book_id,))
        book = await cursor.fetchone()

    amount = round(book[0] / TRX_RATE_USD, 2)
    text = f"🪙 **الدفع بـ TRX**\n\nأرسل {amount} TRX إلى:\n`{TRX_ADDRESS}`\n\nثم أرسل TXID هنا للتأكيد."
    await call.message.edit_text(text, parse_mode="Markdown")
    await state.set_state(BuyStates.waiting_proof)
    await state.update_data(method="trx")

@router.callback_query(F.data == "pay_usdt")
async def pay_usdt(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT price_usd FROM books WHERE id=?", (book_id,))
        book = await cursor.fetchone()

    text = f"💵 **الدفع بـ USDT TRC-20**\n\nأرسل {book[0]} USDT إلى:\n`{USDT_ADDRESS}`\n\nثم أرسل TXID هنا للتأكيد."
    await call.message.edit_text(text, parse_mode="Markdown")
    await state.set_state(BuyStates.waiting_proof)
    await state.update_data(method="usdt")

@router.callback_query(F.data == "pay_binance")
async def pay_binance(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        f"🟡 **Binance Pay**\n\nادفع من هنا: {BINANCE_PAY_LINK}\n\nبعد الدفع أرسل لقطة الشاشة هنا."
    )
    await state.set_state(BuyStates.waiting_proof)
    await state.update_data(method="binance")

# ============ استقبال الإيصال ============
@router.message(BuyStates.waiting_proof)
async def receive_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']
    method = data['method']

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO orders (user_id, book_id, method, proof_msg_id) VALUES (?,?,?)",
            (message.from_user.id, book_id, method, message.message_id)
        )
        order_id = cursor.lastrowid
        await db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ قبول", callback_data=f"approve_{order_id}")],
        [InlineKeyboardButton(text="❌ رفض", callback_data=f"reject_{order_id}")]
    ])

    await bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
    await bot.send_message(ADMIN_ID, f"طلب جديد رقم {order_id}\nالمستخدم: {message.from_user.id}\nالطريقة: {method}", reply_markup=kb)
    await message.answer("✅ تم استلام إيصالك، سيتم المراجعة خلال 24 ساعة.")
    await state.clear()

# ============ قبول/رفض الطلب ============
@router.callback_query(F.data.startswith("approve_"))
async def approve_order(call: CallbackQuery):
    order_id = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id, book_id FROM orders WHERE id=? AND status='pending'", (order_id,))
        order = await cursor.fetchone()
        if not order:
            await call.answer("الطلب غير موجود")
            return
        await db.execute("UPDATE orders SET status='approved' WHERE id=?", (order_id,))
        await db.commit()

    user_id, book_id = order
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT file_path FROM books WHERE id=?", (book_id,))
        book = await cursor.fetchone()

    if book and os.path.exists(book[0]):
        await bot.send_document(user_id, FSInputFile(book[0]), caption="✅ تم تأكيد طلبك، هذا هو الكتاب")
        await call.message.edit_text("✅ تم قبول الطلب وإرسال الكتاب")
    await call.answer("تم")

@router.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    order_id = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
        order = await cursor.fetchone()
        if order:
            await db.execute("UPDATE orders SET status='rejected' WHERE id=?", (order_id,))
            await db.commit()
            await bot.send_message(order[0], "❌ تم رفض طلبك")
    await call.message.edit_text("❌ تم رفض الطلب")
    await call.answer("تم")

# ============ التشغيل ============
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main()) 
