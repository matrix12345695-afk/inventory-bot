import os
import pandas as pd
from datetime import datetime

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
from aiogram.types.web_app_info import WebAppInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import psycopg2
import uvicorn


BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BASE_WEB_URL = "https://inventory-bot-muyu.onrender.com"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL не установлен")

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


# ================= TELEGRAM =================

@dp.message(CommandStart())
async def start(message: Message):

    uid = message.from_user.id

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🛒 Магазин",
                    web_app=WebAppInfo(
                        url=f"{BASE_WEB_URL}/?section=shop&uid={uid}"
                    )
                ),
                KeyboardButton(
                    text="🍳 Кухня",
                    web_app=WebAppInfo(
                        url=f"{BASE_WEB_URL}/?section=kitchen&uid={uid}"
                    )
                ),
            ],
            [
                KeyboardButton(
                    text="🍸 Бар",
                    web_app=WebAppInfo(
                        url=f"{BASE_WEB_URL}/?section=bar&uid={uid}"
                    )
                ),
                KeyboardButton(
                    text="❄ Морозилка",
                    web_app=WebAppInfo(
                        url=f"{BASE_WEB_URL}/?section=freezer&uid={uid}"
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


# ================= SAVE =================

@app.post("/save_inventory")
async def save_inventory(request: Request):

    data = await request.json()

    user_id = data.get("user_id")
    filename = data.get("filename")
    items = data.get("items", [])

    if not user_id or not filename or not items:
        return JSONResponse(status_code=400, content={"error": "Неверные данные"})

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

    return {"count": len(items)}


# ================= LIST =================

@dp.message(F.text == "📊 Инвентаризации")
async def list_inventories(message: Message):

    conn = get_conn()
    cur = conn.cursor()

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

    cur.execute("""
        SELECT article, name, group_name, qty
        FROM inventory
        WHERE filename = %s AND user_id = %s
    """, (filename, callback.from_user.id))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await callback.answer("Данные не найдены", show_alert=True)
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


# ================= STATIC =================

app.mount("/data", StaticFiles(directory="data"), name="data")
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
