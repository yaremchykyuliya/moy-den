import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .backup import run_weekly as run_backups
from .config import load_config
from .content import ContentError, ContentStore
from .db import Database
from .handlers import admin, payments, user
from .nurture import run_forever as run_nurture
from .sales import poll_yookassa
from .tribute import start_server as start_tribute
from .yookassa import YooKassaClient

COMMANDS = [
    BotCommand(command="menu", description="Главное меню"),
    BotCommand(command="my", description="Мои покупки"),
    BotCommand(command="paysupport", description="Вопросы по оплате"),
]


def build_dispatcher(**deps) -> Dispatcher:
    dp = Dispatcher(**deps)
    dp.include_routers(admin.router, payments.router, user.router)
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    try:
        store = ContentStore(config.content_path, config.payment_methods)
    except ContentError as e:
        raise SystemExit(f"Ошибка в {config.content_path.name}: {e}")

    db = Database(config.db_path)
    await db.connect()
    yookassa = (
        YooKassaClient(config.yookassa_shop_id, config.yookassa_secret_key)
        if "yookassa" in config.payment_methods else None
    )

    session = AiohttpSession(proxy=config.telegram_proxy) if config.telegram_proxy else None
    bot = Bot(config.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(config=config, store=store, db=db, yookassa=yookassa)
    await bot.set_my_commands(COMMANDS)

    tasks = [asyncio.create_task(run_nurture(bot, db, store, config.timezone))]
    if config.admin_ids:
        tasks.append(asyncio.create_task(run_backups(bot, db, config)))
    if yookassa:
        tasks.append(asyncio.create_task(poll_yookassa(bot, db, store, config, yookassa)))
    tribute_runner = None
    if "tribute" in config.payment_methods and config.tribute_api_key:
        tribute_runner = await start_tribute(bot, db, store, config)
    elif "tribute" in config.payment_methods:
        logging.warning("Tribute без TRIBUTE_API_KEY: оплата работает, но бот не узнаёт о покупках")
    logging.info(
        "Бот запущен. Оплата: %s. Экранов: %d, продуктов: %d", ", ".join(config.payment_methods),
        len(store.current.screens), len(store.current.products),
    )
    try:
        await dp.start_polling(bot)
    finally:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if yookassa:
            await yookassa.close()
        if tribute_runner:
            await tribute_runner.cleanup()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
