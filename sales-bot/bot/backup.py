"""Копия базы покупателей в Telegram администратору — хранится отдельно от сервера."""
import asyncio
import logging
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import FSInputFile

from .config import Config
from .db import Database

log = logging.getLogger(__name__)

WEEKDAY, HOUR = 0, 10  # понедельник, 10:00 по TIMEZONE


def _snapshot(db_path: Path, target: Path) -> None:
    """Согласованная копия, даже если бот в этот момент пишет в базу."""
    src, dst = sqlite3.connect(db_path), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


async def send_backup(bot: Bot, db: Database, config: Config, admin_ids=None) -> int:
    stats = await db.stats()
    paid = sum(row["sales"] for row in stats["by_product"])
    today = datetime.now(config.timezone)
    caption = (
        f"💾 <b>Копия базы на {today:%d.%m.%Y}</b>\n"
        f"Пользователей: {stats['users']}, оплаченных заказов: {paid}.\n\n"
        "В файле данные покупателей — не пересылай его никому.\n"
        "Как восстановить — в README, раздел «Резервные копии»."
    )
    sent = 0
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / f"shop-{today:%Y-%m-%d}.db"
        await asyncio.to_thread(_snapshot, config.db_path, target)
        for admin_id in admin_ids or config.admin_ids:
            try:
                await bot.send_document(admin_id, FSInputFile(target), caption=caption)
                sent += 1
            except Exception:
                log.warning("Не удалось отправить копию базы админу %s", admin_id)
    return sent


async def weekly_due(db: Database, now: datetime) -> str | None:
    """Ключ недели, если пора отправить и на этой неделе ещё не отправляли."""
    if now.weekday() != WEEKDAY or now.hour < HOUR:
        return None
    year, week, _ = now.isocalendar()
    key = f"backup:{year}-W{week:02d}"
    return None if await db.get_meta(key) else key


async def run_weekly(bot: Bot, db: Database, config: Config, interval: int = 600) -> None:
    while True:
        try:
            key = await weekly_due(db, datetime.now(config.timezone))
            if key and await send_backup(bot, db, config):
                await db.set_meta(key, datetime.now(ZoneInfo("UTC")).isoformat())
        except Exception:
            log.exception("Ошибка еженедельной копии базы")
        await asyncio.sleep(interval)
