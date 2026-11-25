import os
from typing import Dict, List, Optional
import aiohttp
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

pool: Optional[asyncpg.Pool] = None


async def init_db() -> None:
    """PostgreSQL пулини очиш ва жадвал яратиш."""
    global pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable киритилмаган!")

    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                country TEXT DEFAULT 'Europe',
                location TEXT NOT NULL,
                salary TEXT DEFAULT 'Kelishiladi',
                job_type TEXT DEFAULT 'Full-time',
                contact TEXT DEFAULT '',
                url TEXT DEFAULT '',
                source TEXT DEFAULT 'parsed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(title, company)
            )
            """
        )


async def close_db() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


async def save_jobs(jobs: List[Dict]) -> int:
    """Янги вакансияларни базага сақлаш."""
    if pool is None:
        await init_db()

    inserted = 0
    async with pool.acquire() as conn:
        for job in jobs:
            res = await conn.execute(
                """
                INSERT INTO jobs (title, company, country, location, salary, job_type, contact, url, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (title, company) DO NOTHING
                """,
                job["title"],
                job["company"],
                job.get("country", "Europe"),
                job["location"],
                job.get("salary", "Kelishiladi"),
                job.get("job_type", "Full-time"),
                job.get("contact", ""),
                job.get("url", ""),
                job.get("source", "parsed"),
            )
            if res == "INSERT 0 1":
                inserted += 1
    return inserted


def detect_country(location_text: str) -> str:
    loc = location_text.lower()
    mapping = {
        "germany": "Germany",
        "deutschland": "Germany",
        "poland": "Poland",
        "polska": "Poland",
        "czech": "Czech Republic",
        "lithuania": "Lithuania",
        "latvia": "Latvia",
        "estonia": "Estonia",
        "netherlands": "Netherlands",
        "france": "France",
        "spain": "Spain",
        "italy": "Italy",
        "uk": "United Kingdom",
        "united kingdom": "United Kingdom",
        "europe": "Europe",
    }
    for key, country in mapping.items():
        if key in loc:
            return country
    return "Global / Europe"


async def parse_foreign_jobs(limit: int = 30) -> int:
    """Очиқ API манбалардан Европа ва халқаро вакансияларни парсинг қилиш."""
    parsed_jobs: List[Dict] = []

    async with aiohttp.ClientSession() as session:
        # 1-манба: Remotive API
        try:
            async with session.get(
                "https://remotive.com/api/remote-jobs",
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("jobs", [])[:limit]:
                        loc = item.get("candidate_required_location", "Europe / Worldwide")
                        parsed_jobs.append(
                            {
                                "title": item.get("title", "No Title"),
                                "company": item.get("company_name", "Unknown"),
                                "country": detect_country(loc),
                                "location": loc,
                                "salary": item.get("salary") or "Kelishiladi",
                                "job_type": item.get("job_type", "Full-time"),
                                "contact": "",
                                "url": item.get("url", ""),
                                "source": "remotive",
                            }
                        )
        except Exception:
            pass

        # 2-манба: Arbeitnow API (Европа, хусусан Германия вакансиялари)
        try:
            async with session.get(
                "https://www.arbeitnow.com/api/job-board-api",
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("data", [])[:limit]:
                        loc = item.get("location", "Europe")
                        parsed_jobs.append(
                            {
                                "title": item.get("title", "No Title"),
                                "company": item.get("company_name", "Unknown"),
                                "country": detect_country(loc),
                                "location": loc,
                                "salary": "Kelishiladi",
                                "job_type": ", ".join(item.get("job_types", [])) or "Full-time",
                                "contact": "",
                                "url": item.get("url", ""),
                                "source": "arbeitnow",
                            }
                        )
        except Exception:
            pass

    return await save_jobs(parsed_jobs)


async def get_jobs(
    search: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    if pool is None:
        await init_db()

    conditions = ["1=1"]
    params = []
    idx = 1

    if search:
        conditions.append(f"(LOWER(title) LIKE ${idx} OR LOWER(company) LIKE ${idx} OR LOWER(location) LIKE ${idx})")
        params.append(f"%{search.lower()}%")
        idx += 1

    if country and country.lower() != "all":
        conditions.append(f"LOWER(country) LIKE ${idx}")
        params.append(f"%{country.lower()}%")
        idx += 1

    params.append(limit)
    query = f"""
        SELECT id, title, company, country, location, salary, job_type, contact, url, source
        FROM jobs
        WHERE {' AND '.join(conditions)}
        ORDER BY id DESC
        LIMIT ${idx}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]
