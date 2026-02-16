import os
import sqlite3
import pandas as pd
import asyncio
import logging
import threading
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    FSInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import CommandStart
from aiogram.types.web_app_info import WebAppInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn


# ==========================
# CONFIG
# ==========================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен")

BASE_WEB_URL = "https://inventory-bot-muyu.onrender.com"


# ==========================
# PATHS
# ==========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "inventory.db")
INVENTORY_FOLDER = os.path.join(BASE_DIR, "inventories")

os.makedirs(INVENTORY_FOLDER, exist_ok=True)


# ==========================
# LOGGING
# ==========================

logging.basicConfig(level=logging.INFO)


# ==========================
# INIT
# ==========================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            filename TEXT,
            article TEXT,
            group_name TEXT,
            qty REAL,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ==========================
# TELEGRAM START
# ==========================

@dp.message(CommandStart())
async def start(message: Message):

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🛒 Магазин",
                    web_app=WebAppInfo(
                        url=f"{BASE_WEB_URL}/?section=shop"
                    )
                ),
                KeyboardButton(
                    text="🍳 Кухня",
                    web_app=WebAppInfo(
                        url=f"{BASE_WEB_URL}/?section=kitchen"
                    )
                ),
            ],
            [
                KeyboardButton(
                    text="🍸 Бар",
                    web_app=WebAppInfo(
                        url=f"{BASE_WEB_URL}/?section=bar"
                    )
                ),
                KeyboardButton(
                    text="❄ Морозилка",
                    web_app=WebAppInfo(
                        url=f"{BASE_WEB_URL}/?section=freezer"
                    )
                ),
            ],
            [
                KeyboardButton(text="📊 Инвентаризации")
            ]
        ],
        resize_keyboard=True
    )

    await message.answer("Выберите раздел:", reply_markup=keyboard)


# ==========================
# SAVE INVENTORY
# ==========================

@app.post("/save_inventory")
async def save_inventory(request: Request):

    data = await request.json()

    user_id = data.get("user_id")
    filename = data.get("filename")
    items = data.get("items", [])

    if not user_id or not filename or not items:
        return JSONResponse(status_code=400, content={"error": "Неверные данные"})

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for item in items:
        cur.execute("""
            INSERT INTO inventory
            (user_id, filename, article, group_name, qty, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            filename,
            item["article"],
            item["group"],
            item["qty"],
            datetime.now().isoformat()
        ))

    conn.commit()
    conn.close()

    # создаём Excel
    df = pd.DataFrame(items)

    excel_path = os.path.join(
        INVENTORY_FOLDER,
        f"{filename}.xlsx"
    )

    df.to_excel(excel_path, index=False)

    return {"count": len(items)}


# ==========================
# LIST INVENTORIES
# ==========================

@dp.message(F.text == "📊 Инвентаризации")
async def list_inventories(message: Message):

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT filename
        FROM inventory
        WHERE user_id = ?
        ORDER BY id DESC
    """, (message.from_user.id,))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await message.answer("Нет сохранённых инвентаризаций.")
        return

    buttons = []

    for row in rows:
        filename = row[0]
        buttons.append([
            InlineKeyboardButton(
                text=f"📁 {filename}",
                callback_data=f"export::{filename}"
            )
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer("Выберите инвентаризацию:", reply_markup=keyboard)


# ==========================
# EXPORT TO EXCEL
# ==========================

@dp.callback_query(F.data.startswith("export::"))
async def export_inventory(callback: CallbackQuery):

    filename = callback.data.split("::")[1]

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT article, group_name, qty
        FROM inventory
        WHERE filename = ? AND user_id = ?
    """, (filename, callback.from_user.id))

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await callback.answer("Данные не найдены", show_alert=True)
        return

    df = pd.DataFrame(rows, columns=["Артикул", "Группа", "Количество"])

    excel_path = os.path.join(
        INVENTORY_FOLDER,
        f"{filename}.xlsx"
    )

    df.to_excel(excel_path, index=False)

    await callback.message.answer_document(
        FSInputFile(excel_path),
        caption=f"Инвентаризация: {filename}"
    )

    await callback.answer()


# ==========================
# STATIC
# ==========================

app.mount("/data", StaticFiles(directory="data"), name="data")
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# ==========================
# START
# ==========================

def start_bot():
    asyncio.run(dp.start_polling(bot))


if __name__ == "__main__":
    threading.Thread(target=start_bot).start()
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
