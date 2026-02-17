import os
import pandas as pd
from datetime import datetime, date

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    FSInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Update
)
from aiogram.filters import CommandStart

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import psycopg2
import uvicorn


BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BASE_WEB_URL = "https://inventory-bot-muyu.onrender.com"

ADMIN_IDS = [502438855]  # <-- ВСТАВЬ СВОЙ TELEGRAM ID


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()


# ================= DATABASE =================

def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            filename TEXT,
            article TEXT,
            name TEXT,
            group_name TEXT,
            qty NUMERIC,
            created_at TIMESTAMP
        );
    """)

    conn.commit()
    cur.close()
    conn.close()


init_db()


# ================= START =================

@dp.message(CommandStart())
async def start(message: Message):

    uid = message.from_user.id

    buttons = [
        [KeyboardButton(text="📊 Инвентаризации")]
    ]

    if uid in ADMIN_IDS:
        buttons.append([KeyboardButton(text="👑 Админ панель")])

    keyboard = ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )

    await message.answer("Главное меню:", reply_markup=keyboard)


# ================= SAVE =================

@app.post("/save_inventory")
async def save_inventory(request: Request):

    data = await request.json()

    user_id = data.get("user_id")
    filename = data.get("filename")
    items = data.get("items", [])

    conn = get_conn()
    cur = conn.cursor()

    for item in items:
        cur.execute("""
            INSERT INTO inventory
            (user_id, filename, article, name, group_name, qty, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            filename,
            item["article"],
            item["name"],
            item["group"],
            item["qty"],
            datetime.now()
        ))

    conn.commit()
    cur.close()
    conn.close()

    return {"ok": True}


# ================= LIST =================

@dp.message(F.text == "📊 Инвентаризации")
async def list_inventories(message: Message):

    conn = get_conn()
    cur = conn.cursor()

    if message.from_user.id in ADMIN_IDS:
        cur.execute("""
            SELECT DISTINCT filename
            FROM inventory
            ORDER BY filename DESC
        """)
    else:
        cur.execute("""
            SELECT DISTINCT filename
            FROM inventory
            WHERE user_id = %s
            ORDER BY filename DESC
        """, (message.from_user.id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await message.answer("Нет сохранённых инвентаризаций.")
        return

    buttons = [
        [InlineKeyboardButton(text=f"📁 {row[0]}", callback_data=f"export::{row[0]}")]
        for row in rows
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выберите инвентаризацию:", reply_markup=keyboard)


# ================= EXPORT =================

@dp.callback_query(F.data.startswith("export::"))
async def export_inventory(callback: CallbackQuery):

    filename = callback.data.split("::")[1]

    conn = get_conn()
    cur = conn.cursor()

    if callback.from_user.id in ADMIN_IDS:
        cur.execute("""
            SELECT article, name, group_name, qty
            FROM inventory
            WHERE filename = %s
        """, (filename,))
    else:
        cur.execute("""
            SELECT article, name, group_name, qty
            FROM inventory
            WHERE filename = %s AND user_id = %s
        """, (filename, callback.from_user.id))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await callback.answer("Нет доступа", show_alert=True)
        return

    df = pd.DataFrame(rows, columns=[
        "Артикул",
        "Наименование",
        "Группа",
        "Количество"
    ])

    file_path = f"/tmp/{filename}.xlsx"
    df.to_excel(file_path, index=False)

    await callback.message.answer_document(
        FSInputFile(file_path),
        caption=f"Инвентаризация: {filename}"
    )

    await callback.answer()


# ================= ADMIN PANEL =================

@dp.message(F.text == "👑 Админ панель")
async def admin_panel(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить инвентаризацию", callback_data="admin_delete")],
        [InlineKeyboardButton(text="📅 Фильтр по дате", callback_data="admin_filter")]
    ])

    await message.answer("Админ панель:", reply_markup=keyboard)


# ================= DELETE =================

@dp.callback_query(F.data == "admin_delete")
async def admin_delete_list(callback: CallbackQuery):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT filename
        FROM inventory
        ORDER BY filename DESC
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    buttons = [
        [InlineKeyboardButton(text=row[0], callback_data=f"delete::{row[0]}")]
        for row in rows
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer("Выберите файл для удаления:", reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data.startswith("delete::"))
async def delete_inventory(callback: CallbackQuery):

    filename = callback.data.split("::")[1]

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM inventory WHERE filename = %s", (filename,))
    conn.commit()

    cur.close()
    conn.close()

    await callback.message.answer(f"Инвентаризация {filename} удалена.")
    await callback.answer()


# ================= FILTER =================

@dp.callback_query(F.data == "admin_filter")
async def admin_filter(callback: CallbackQuery):
    await callback.message.answer("Введите дату в формате YYYY-MM-DD")
    await callback.answer()


@dp.message()
async def filter_by_date(message: Message):

    if message.from_user.id not in ADMIN_IDS:
        return

    try:
        filter_date = datetime.strptime(message.text, "%Y-%m-%d").date()
    except:
        return

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT filename
        FROM inventory
        WHERE DATE(created_at) = %s
    """, (filter_date,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await message.answer("За эту дату нет инвентаризаций.")
        return

    buttons = [
        [InlineKeyboardButton(text=row[0], callback_data=f"export::{row[0]}")]
        for row in rows
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Инвентаризации за дату:", reply_markup=keyboard)


# ================= WEBHOOK =================

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(f"{BASE_WEB_URL}/webhook")


app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
