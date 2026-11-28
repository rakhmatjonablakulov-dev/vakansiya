import asyncio
import html
import json
import os
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import quote
from urllib.request import Request, urlopen

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DATABASE_URL = os.environ.get("DATABASE_URL", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")

db_pool: Optional[asyncpg.Pool] = None


def _send_telegram_sync(text: str) -> None:
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as resp:
        resp.read()


async def notify_admin(text: str) -> None:
    try:
        await asyncio.to_thread(_send_telegram_sync, text)
    except Exception as e:
        print(f"Telegram send error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    if DATABASE_URL:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    country TEXT,
                    salary TEXT,
                    contact TEXT,
                    description TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
    yield
    if db_pool:
        await db_pool.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class JobCreate(BaseModel):
    title: str
    country: Optional[str] = ""
    salary: Optional[str] = ""
    contact: Optional[str] = ""
    description: Optional[str] = ""


@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/jobs")
async def get_jobs():
    if not db_pool:
        return []
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, country, salary, contact, description, created_at "
            "FROM jobs ORDER BY id DESC LIMIT 100"
        )
        return [dict(r) for r in rows]


@app.post("/api/jobs")
async def create_job(job: JobCreate):
    job_id = None
    if db_pool:
        async with db_pool.acquire() as conn:
            job_id = await conn.fetchval(
                """
                INSERT INTO jobs (title, country, salary, contact, description)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                job.title,
                job.country,
                job.salary,
                job.contact,
                job.description,
            )

    msg = (
        f"🆕 <b>Новая заявка / вакансия</b>"
        f"{f' (#{job_id})' if job_id else ''}\n\n"
        f"📌 <b>Название:</b> {html.escape(job.title)}\n"
        f"🌍 <b>Страна:</b> {html.escape(job.country or '-')}\n"
        f"💰 <b>Зарплата:</b> {html.escape(job.salary or '-')}\n"
        f"📞 <b>Контакт:</b> {html.escape(job.contact or '-')}\n"
        f"📝 <b>Описание:</b> {html.escape(job.description or '-')}"
    )
    asyncio.create_task(notify_admin(msg))
    return {"ok": True, "id": job_id}
