import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from . import keyboards as kb
from .content import ContentStore
from .db import Database

log = logging.getLogger(__name__)

WINDOW_MINUTES = 36 * 60  # шаг не уйдёт тем, кто забрал гайд намного раньше (например, если шаг добавили позже)
SEND_INTERVAL = 0.05


def in_send_hours(now: datetime, hours: tuple[int, int]) -> bool:
    return hours[0] <= now.hour < hours[1]


async def run_once(bot: Bot, db: Database, store: ContentStore, tz: ZoneInfo) -> int:
    content = store.current
    if not content.nurture or not in_send_hours(datetime.now(tz), content.nurture_hours):
        return 0
    sent = 0
    for step in content.nurture:
        users = await db.nurture_due(step.id, step.delay_minutes, WINDOW_MINUTES, step.skip_if_bought)
        for user_id in users:
            try:
                await bot.send_message(user_id, step.screen.text, reply_markup=kb.screen(step.screen))
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                continue
            except TelegramForbiddenError:
                await db.mark_blocked(user_id)
                continue
            except Exception:
                # Помечаем отправленным, чтобы битый текст не повторялся каждую минуту
                log.exception("Прогрев %s: не отправилось пользователю %s", step.id, user_id)
                await db.mark_nurture_sent(user_id, step.id)
                continue
            await db.mark_nurture_sent(user_id, step.id)
            sent += 1
            await asyncio.sleep(SEND_INTERVAL)
    return sent


async def run_forever(bot: Bot, db: Database, store: ContentStore, tz: ZoneInfo, interval: int = 60) -> None:
    while True:
        try:
            sent = await run_once(bot, db, store, tz)
            if sent:
                log.info("Прогрев: отправлено %d сообщений", sent)
        except Exception:
            log.exception("Ошибка в прогреве")
        await asyncio.sleep(interval)
