import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from parsing import close_db, get_jobs, init_db, parse_foreign_jobs, save_jobs

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
MONETAG_ZONE_ID = os.getenv("MONETAG_ZONE_ID", "12197315")

dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Иш топиш / Эълон бериш (Mini App)",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )
    await message.answer(
        "🌍 <b>Европа ва Хорижий Ишлар Платформаси</b>\n\n"
        "• Иш қидирувчилар учун: Европа ва хорижий давлатлардаги сўнгги вакансиялар.\n"
        "• Иш берувчилар учун: тўғридан-тўғри вакансия жойлаштириш.\n\n"
        "Барча хизматлардан фойдаланиш учун қуйидаги тугма орқали <b>Mini App</b>'ни очинг 👇",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def run_bot() -> None:
    if not BOT_TOKEN:
        return
    bot = Bot(token=BOT_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    bot_task = asyncio.create_task(run_bot())
    yield
    bot_task.cancel()
    await close_db()


app = FastAPI(title="Europe Jobs Mini App", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class JobCreate(BaseModel):
    title: str
    company: str
    country: str = "Europe"
    location: str
    salary: str = "Kelishiladi"
    job_type: str = "Full-time"
    contact: str = ""
    url: str = ""


@app.get("/")
async def serve_index() -> FileResponse:
    return FileResponse("index.html")


@app.get("/api/config")
async def get_config():
    return {"monetag_zone_id": MONETAG_ZONE_ID}


@app.get("/api/jobs")
async def api_list_jobs(
    search: Optional[str] = Query(default=None),
    country: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    jobs = await get_jobs(search=search, country=country, limit=limit)
    return {"count": len(jobs), "jobs": jobs}


@app.post("/api/jobs")
async def api_create_job(payload: JobCreate):
    inserted = await save_jobs(
        [
            {
                "title": payload.title.strip(),
                "company": payload.company.strip(),
                "country": payload.country.strip() or "Europe",
                "location": payload.location.strip(),
                "salary": payload.salary.strip() or "Kelishiladi",
                "job_type": payload.job_type.strip() or "Full-time",
                "contact": payload.contact.strip(),
                "url": payload.url.strip(),
                "source": "employer_miniapp",
            }
        ]
    )
    return {"status": "ok", "inserted": inserted}


@app.post("/api/parse")
async def api_parse_jobs(limit: int = Query(default=30, ge=1, le=100)):
    inserted = await parse_foreign_jobs(limit=limit)
    return {"status": "ok", "inserted": inserted}
