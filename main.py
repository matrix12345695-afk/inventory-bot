import os
import logging
from datetime import datetime
from io import BytesIO

import psycopg2
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    InputFile,
    Update
)
from aiogram.filters import CommandStart
from openpyxl import Workbook

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BASE_WEB_URL = os.getenv("BASE_WEB_URL")

ADMIN_IDS = [502438855]

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL не установлен")

if not BASE_WEB_URL:
    raise ValueError("BASE_WEB_URL не установлен")

# ================= INIT =================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

# ================= STATIC =================

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/data", StaticFiles(directory="data"), name="data")

@app.get("/")
async def index():
    return FileResponse("static/index.html")

# ================= DB =================

def get_conn():
    return psycopg2.connect(DATABASE_URL)

# ================= MAIN MENU =================

def main_menu(uid):
    keyboard = [
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
        [KeyboardButton(text="📊 Инвентаризации")]
    ]

    if uid in ADMIN_IDS:
        keyboard.append([KeyboardButton(text="🛠 Админ панель")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Главное меню:", reply_markup=main_menu(message.from_user.id))


# ================= SAVE INVENTORY =================

@app.post("/save_inventory")
async def save_inventory(request: Request):
    data = await request.json()

    user_id = data.get("user_id")
    name = data.get("filename")
    items = data.get("items", [])

    if not user_id or not name:
        return {"error": "invalid data"}

    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now()

    for item in items:
        cur.execute("""
            INSERT INTO inventory
            (user_id, name, article, group_name, qty, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            name,
            item["article"],
            item["group"],
            item["qty"],
            now
        ))

    conn.commit()
    cur.close()
    conn.close()

    return {"status": "ok"}


# ================= LIST INVENTORIES BUTTONS =================

@dp.message(F.text == "📊 Инвентаризации")
async def list_inventories(message: Message):
    user_id = message.from_user.id

    conn = get_conn()
    cur = conn.cursor()

    if user_id in ADMIN_IDS:
        cur.execute("SELECT DISTINCT name FROM inventory ORDER BY name DESC")
    else:
        cur.execute(
            "SELECT DISTINCT name FROM inventory WHERE user_id = %s ORDER BY name DESC",
            (user_id,)
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await message.answer("Нет сохранённых инвентаризаций.")
        return

    buttons = [[KeyboardButton(text=f"📁 {row[0]}")] for row in rows]
    buttons.append([KeyboardButton(text="🔙 Главное меню")])

    await message.answer(
        "Выберите инвентаризацию:",
        reply_markup=ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    )


# ================= EXPORT =================

@dp.message(F.text.startswith("📁 "))
async def export_inventory(message: Message):
    name = message.text.replace("📁 ", "")
    user_id = message.from_user.id

    conn = get_conn()
    cur = conn.cursor()

    if user_id in ADMIN_IDS:
        cur.execute("SELECT article, group_name, qty FROM inventory WHERE name = %s", (name,))
    else:
        cur.execute(
            "SELECT article, group_name, qty FROM inventory WHERE name = %s AND user_id = %s",
            (name, user_id)
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.append(["Артикул", "Группа", "Количество"])

    for row in rows:
        ws.append(row)

    file_stream = BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    await message.answer_document(
        InputFile(file_stream, filename=f"{name}.xlsx")
    )


# ================= ADMIN PANEL =================

@dp.message(F.text == "🛠 Админ панель")
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    keyboard = [
        [KeyboardButton(text="🗑 Удалить инвентаризацию")],
        [KeyboardButton(text="🔙 Главное меню")]
    ]

    await message.answer(
        "Админ панель:",
        reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    )


# ================= DELETE WITH BUTTONS =================

@dp.message(F.text == "🗑 Удалить инвентаризацию")
async def choose_delete_inventory(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT name FROM inventory ORDER BY name DESC")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    if not rows:
        await message.answer("Нет инвентаризаций для удаления.")
        return

    buttons = [[KeyboardButton(text=f"❌ {row[0]}")] for row in rows]
    buttons.append([KeyboardButton(text="🔙 Главное меню")])

    await message.answer(
        "Выберите что удалить:",
        reply_markup=ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    )


@dp.message(F.text.startswith("❌ "))
async def delete_inventory(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    name = message.text.replace("❌ ", "")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM inventory WHERE name = %s", (name,))
    conn.commit()

    cur.close()
    conn.close()

    await message.answer(f"Инвентаризация '{name}' удалена.")


# ================= BACK =================

@dp.message(F.text == "🔙 Главное меню")
async def back_to_menu(message: Message):
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu(message.from_user.id)
    )


# ================= WEBHOOK =================

@app.post("/webhook")
async def telegram_webhook(request: Request):
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}


# ================= STARTUP =================

@app.on_event("startup")
async def startup():
    await bot.set_webhook(f"{BASE_WEB_URL}/webhook")
    logging.info("Webhook установлен")


# ================= RUN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
