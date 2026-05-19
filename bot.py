import asyncio
import asyncpg
import requests
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ============ متغيرات البيئة ============
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

BANK_INFO = os.getenv("BANK_INFO")
TRX_ADDRESS = os.getenv("TRX_ADDRESS")
USDT_ADDRESS = os.getenv("USDT_ADDRESS")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY")
USDT_CONTRACT = os.getenv("USDT_CONTRACT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
BINANCE_PAY_LINK = os.getenv("BINANCE_PAY_LINK")
TRX_RATE_USD = float(os.getenv("TRX_RATE_USD", "0.15"))

DATABASE_URL = os.getenv("DATABASE_URL")  # من Supabase

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ============ تعريف الحالات ============
class BuyStates(StatesGroup):
    waiting_proof = State()

class BroadcastStates(StatesGroup):
    waiting_message = State()

class EditBookStates(StatesGroup):
    selecting_book = State()
    selecting_field = State()
    new_title = State()
    new_author = State()
    new_price = State()

class RegisterBookStates(StatesGroup):
    waiting_title = State()
    waiting_author = State()
    waiting_price = State()
    waiting_filepath = State()

# ============ دوال قاعدة البيانات ============
async def get_db_connection():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await get_db_connection()
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            title TEXT,
            author TEXT,
            price_usd REAL,
            file_path TEXT
        )
    ''')
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            book_id INTEGER,
            method TEXT,
            status TEXT DEFAULT 'pending',
            proof_msg_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    await conn.close()

async def get_book_by_id(book_id: int):
    conn = await get_db_connection()
    row = await conn.fetchrow("SELECT title, author, price_usd, file_path FROM books WHERE id = $1", book_id)
    await conn.close()
    return row

async def count_sold_books():
    conn = await get_db_connection()
    count = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status = 'paid'")
    await conn.close()
    return count or 0

async def total_revenue():
    conn = await get_db_connection()
    total = await conn.fetchval('''
        SELECT COALESCE(SUM(price_usd), 0) FROM books
        WHERE id IN (SELECT book_id FROM orders WHERE status = 'paid')
    ''')
    await conn.close()
    return float(total)

async def sync_books_from_folder():
    books_folder = "books"
    if not os.path.exists(books_folder):
        os.makedirs(books_folder, exist_ok=True)
        print(f"✅ تم إنشاء مجلد {books_folder}")
        return
    pdf_files = [f for f in os.listdir(books_folder) if f.endswith('.pdf')]
    if not pdf_files:
        print("لا توجد ملفات PDF في مجلد books")
        return
    conn = await get_db_connection()
    for pdf in pdf_files:
        file_path = os.path.join(books_folder, pdf)
        exists = await conn.fetchval("SELECT id FROM books WHERE file_path = $1", file_path)
        if exists:
            continue
        title = pdf.replace('.pdf', '').replace('_', ' ')
        await conn.execute(
            "INSERT INTO books (title, author, price_usd, file_path) VALUES ($1, $2, $3, $4)",
            title, "غير معروف", 0.0, file_path
        )
        print(f"✅ تم إضافة الكتاب تلقائياً: {title}")
    await conn.close()

# ============ أوامر البوت ============
@router.message(CommandStart())
async def start(message: Message):
    conn = await get_db_connection()
    books = await conn.fetch("SELECT id, title, author, price_usd FROM books")
    await conn.close()
    if not books:
        await message.answer("📚 لا يوجد كتب حالياً.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{b['title']} - {b['author']} | ${b['price_usd']}", callback_data=f"book_{b['id']}")]
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
    conn = await get_db_connection()
    order_id = await conn.fetchval(
        "INSERT INTO orders (user_id, book_id, method, proof_msg_id, status) VALUES ($1, $2, 'bank', $3, 'pending') RETURNING id",
        message.from_user.id, book_id, message.message_id
    )
    await conn.close()
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
    conn = await get_db_connection()
    order = await conn.fetchrow("SELECT user_id, book_id FROM orders WHERE id=$1 AND status='pending'", order_id)
    if not order:
        await call.answer("الطلب غير موجود أو تم معالجته")
        await conn.close()
        return
    await conn.execute("UPDATE orders SET status='paid' WHERE id=$1", order_id)
    await conn.close()
    book = await get_book_by_id(order['book_id'])
    if not book or not os.path.exists(book['file_path']):
        await bot.send_message(order['user_id'], "⚠️ ملف الكتاب غير موجود. تواصل مع الأدمن.")
        await call.message.edit_text("⚠️ فشل الإرسال: الملف غير موجود.")
        return
    await bot.send_document(order['user_id'], FSInputFile(book['file_path']), caption=f"✅ تم تأكيد الدفع!\n📖 {book['title']} - {book['author']}")
    await call.message.edit_text("✅ تمت الموافقة وإرسال الكتاب.")

@router.callback_query(F.data.startswith("reject_"))
async def reject_order(call: CallbackQuery):
    order_id = int(call.data.split("_")[1])
    conn = await get_db_connection()
    order = await conn.fetchrow("SELECT user_id FROM orders WHERE id=$1", order_id)
    if order:
        await conn.execute("UPDATE orders SET status='rejected' WHERE id=$1", order_id)
        await bot.send_message(order['user_id'], "❌ تم رفض إثبات الدفع. تواصل مع الأدمن.")
    await conn.close()
    await call.message.edit_text("❌ تم رفض الطلب.")

@router.callback_query(F.data == "pay_trx")
async def pay_trx(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    book_id = data['book_id']
    book = await get_book_by_id(book_id)
    if not book:
        await call.answer("الكتاب غير موجود")
        return
    amount_trx = round(book['price_usd'] / TRX_RATE_USD, 2)
    await call.message.edit_text(
        f"🪙 **الدفع بـ TRX**\n\nأرسل **{amount_trx} TRX** إلى:\n`{TRX_ADDRESS}`\n\nالمبلغ يعادل ${book['price_usd']}\n**هام:** اكتب `{call.from_user.id}` في خانة Memo.\nبعد الإرسال اضغط 'تحققت'.\n⚠️ شبكة TRON فقط.",
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
                    conn = await get_db_connection()
                    await conn.execute("INSERT INTO orders (user_id, book_id, method, status) VALUES ($1, $2, 'trx', 'paid')", user_id, book_id)
                    await conn.close()
                    if os.path.exists(book['file_path']):
                        await bot.send_document(user_id, FSInputFile(book['file_path']), caption=f"✅ تم الدفع بـ TRX!\n📖 {book['title']}")
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
        f"💵 **الدفع بـ USDT (TRC-20)**\n\nأرسل **${book['price_usd']} USDT** إلى:\n`{USDT_ADDRESS}`\n\n⚠️ شبكة TRC-20 فقط.\nبعد الإرسال اضغط 'تحققت'.",
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
                if value >= book['price_usd']:
                    conn = await get_db_connection()
                    existing = await conn.fetchval("SELECT id FROM orders WHERE user_id=$1 AND book_id=$2 AND status='paid'", user_id, book_id)
                    if not existing:
                        await conn.execute("INSERT INTO orders (user_id, book_id, method, status) VALUES ($1, $2, 'usdt', 'paid')", user_id, book_id)
                    await conn.close()
                    if os.path.exists(book['file_path']):
                        await bot.send_document(user_id, FSInputFile(book['file_path']), caption=f"✅ تم الدفع بـ USDT!\n📖 {book['title']}")
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
@router.message(Command("registerbook"))
async def registerbook_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("أدخل عنوان الكتاب:")
    await state.set_state(RegisterBookStates.waiting_title)

@router.message(RegisterBookStates.waiting_title)
async def reg_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("أدخل اسم المؤلف:")
    await state.set_state(RegisterBookStates.waiting_author)

@router.message(RegisterBookStates.waiting_author)
async def reg_author(message: Message, state: FSMContext):
    await state.update_data(author=message.text.strip())
    await message.answer("أدخل السعر (بالدولار، مثال 5.99):")
    await state.set_state(RegisterBookStates.waiting_price)

@router.message(RegisterBookStates.waiting_price)
async def reg_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
        await state.update_data(price=price)
        await message.answer("أدخل المسار النسبي للملف (مثال: books/sejonalmhd.pdf):")
        await state.set_state(RegisterBookStates.waiting_filepath)
    except:
        await message.answer("السعر غير صحيح، أدخل رقماً (مثال 5.99):")

@router.message(RegisterBookStates.waiting_filepath)
async def reg_filepath(message: Message, state: FSMContext):
    file_path = message.text.strip()
    if not file_path.startswith("books/"):
        file_path = "books/" + file_path
    if not os.path.exists(file_path):
        await message.answer(f"⚠️ الملف غير موجود: {file_path}\nتأكد من رفع الملف إلى مجلد books في GitHub ثم إعادة نشر البوت، أو اكتب المسار الصحيح.")
        return
    data = await state.get_data()
    conn = await get_db_connection()
    await conn.execute(
        "INSERT INTO books (title, author, price_usd, file_path) VALUES ($1, $2, $3, $4)",
        data['title'], data['author'], data['price'], file_path
    )
    await conn.close()
    await message.answer(f"✅ تم إضافة الكتاب **{data['title']}** بواسطة {data['author']} بسعر ${data['price']}")
    await state.clear()

@router.message(Command("editbook"))
async def editbook_list(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    conn = await get_db_connection()
    books = await conn.fetch("SELECT id, title FROM books")
    await conn.close()
    if not books:
        await message.answer("لا توجد كتب.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=row['title'], callback_data=f"editbook_{row['id']}")] for row in books
    ])
    await message.answer("اختر الكتاب الذي تريد تعديله:", reply_markup=kb)
    await state.set_state(EditBookStates.selecting_book)

@router.callback_query(EditBookStates.selecting_book, F.data.startswith("editbook_"))
async def editbook_field(call: CallbackQuery, state: FSMContext):
    book_id = int(call.data.split("_")[1])
    await state.update_data(book_id=book_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="تعديل العنوان", callback_data="field_title")],
        [InlineKeyboardButton(text="تعديل المؤلف", callback_data="field_author")],
        [InlineKeyboardButton(text="تعديل السعر", callback_data="field_price")]
    ])
    await call.message.edit_text("اختر الحقل الذي تريد تعديله:", reply_markup=kb)
    await state.set_state(EditBookStates.selecting_field)

@router.callback_query(EditBookStates.selecting_field, F.data.startswith("field_"))
async def editbook_newvalue(call: CallbackQuery, state: FSMContext):
    field = call.data.split("_")[1]
    await state.update_data(field=field)
    if field == "title":
        await call.message.edit_text("أرسل العنوان الجديد:")
        await state.set_state(EditBookStates.new_title)
    elif field == "author":
        await call.message.edit_text("أرسل المؤلف الجديد:")
        await state.set_state(EditBookStates.new_author)
    elif field == "price":
        await call.message.edit_text("أرسل السعر الجديد (رقم):")
        await state.set_state(EditBookStates.new_price)

@router.message(EditBookStates.new_title)
async def update_title(message: Message, state: FSMContext):
    data = await state.get_data()
    conn = await get_db_connection()
    await conn.execute("UPDATE books SET title=$1 WHERE id=$2", message.text.strip(), data['book_id'])
    await conn.close()
    await message.answer(f"✅ تم تحديث العنوان إلى: {message.text.strip()}")
    await state.clear()

@router.message(EditBookStates.new_author)
async def update_author(message: Message, state: FSMContext):
    data = await state.get_data()
    conn = await get_db_connection()
    await conn.execute("UPDATE books SET author=$1 WHERE id=$2", message.text.strip(), data['book_id'])
    await conn.close()
    await message.answer(f"✅ تم تحديث المؤلف إلى: {message.text.strip()}")
    await state.clear()

@router.message(EditBookStates.new_price)
async def update_price(message: Message, state: FSMContext):
    try:
        new_price = float(message.text.strip())
        data = await state.get_data()
        conn = await get_db_connection()
        await conn.execute("UPDATE books SET price_usd=$1 WHERE id=$2", new_price, data['book_id'])
        await conn.close()
        await message.answer(f"✅ تم تحديث السعر إلى: ${new_price}")
    except:
        await message.answer("السعر غير صحيح، أدخل رقماً.")
        return
    await state.clear()

@router.message(Command("delbook"))
async def delbook(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    conn = await get_db_connection()
    books = await conn.fetch("SELECT id, title FROM books")
    await conn.close()
    if not books:
        await message.answer("لا توجد كتب.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b['title'], callback_data=f"delbook_{b['id']}")] for b in books
    ])
    await message.answer("اختر الكتاب لحذفه:", reply_markup=kb)

@router.callback_query(F.data.startswith("delbook_"))
async def confirm_delbook(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("غير مصرح")
        return
    book_id = int(call.data.split("_")[1])
    conn = await get_db_connection()
    await conn.execute("DELETE FROM books WHERE id=$1", book_id)
    await conn.close()
    await call.message.edit_text("✅ تم حذف الكتاب.")

@router.message(Command("stats"))
async def stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("للمشرف فقط.")
        return
    sold = await count_sold_books()
    revenue = await total_revenue()
    conn = await get_db_connection()
    pending = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status='pending'")
    await conn.close()
    await message.answer(f"📊 **الإحصائيات**\n📚 مباع: {sold}\n💰 الأرباح: ${revenue}\n⏳ معلقة: {pending}", parse_mode="Markdown")

@router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("أرسل الرسالة (نص، صورة، ملف) ليتم نشرها لجميع المستخدمين.")
    await state.set_state(BroadcastStates.waiting_message)

@router.message(BroadcastStates.waiting_message, F.text | F.photo | F.document)
async def send_broadcast(message: Message, state: FSMContext):
    conn = await get_db_connection()
    users = await conn.fetch("SELECT DISTINCT user_id FROM orders")
    await conn.close()
    if not users:
        await message.answer("لا يوجد مستخدمون.")
        await state.clear()
        return
    success = 0
    for user in users:
        user_id = user['user_id']
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
    if message.from_user.id != ADMIN_ID:
        return
    conn = await get_db_connection()
    pending = await conn.fetch("SELECT id, user_id, book_id, method FROM orders WHERE status='pending'")
    await conn.close()
    if not pending:
        await message.answer("✅ لا توجد طلبات معلقة.")
        return
    text = "\n".join([f"طلب #{p['id']} | مستخدم {p['user_id']} | كتاب {p['book_id']} | {p['method']}" for p in pending])
    await message.answer(f"**الطلبات المعلقة:**\n{text}", parse_mode="Markdown")

# ============ أمر إضافة كتاب عبر رفع الملف مباشرة (اختياري) ============
@router.message(Command("addbook"))
async def addbook_instruction(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "📚 **إضافة كتاب برفع الملف مباشرة**\n\n"
        "أرسل ملف PDF مع كابشن بهذا الشكل:\n"
        "`العنوان | المؤلف | السعر`\n\n"
        "مثال:\n"
        "`الأرض | نجيب محفوظ | 5`\n\n"
        "سيتم حفظ الملف وإضافة الكتاب."
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
    try:
        file = await bot.get_file(message.document.file_id)
        await bot.download_file(file.file_path, file_path)
    except Exception as e:
        await message.answer(f"❌ فشل تحميل الملف: {str(e)}")
        return
    conn = await get_db_connection()
    await conn.execute(
        "INSERT INTO books (title, author, price_usd, file_path) VALUES ($1, $2, $3, $4)",
        title, author, price, file_path
    )
    await conn.close()
    await message.answer(f"✅ تم إضافة الكتاب **{title}** للمؤلف **{author}** بسعر ${price}")

# ============ تشغيل البوت ============
async def main():
    await init_db()
    await sync_books_from_folder()
    print("Bot started polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
