import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .config import load_config
from .content import ContentError, ContentStore
from .db import Database
from .handlers import admin, payments, user
from .sales import poll_yookassa
from .yookassa import YooKassaClient

COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="catalog", description="Каталог продуктов"),
    BotCommand(command="my", description="Мои покупки"),
    BotCommand(command="support", description="Поддержка"),
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
        store = ContentStore(config.content_path, config.payment_provider)
    except ContentError as e:
        raise SystemExit(f"Ошибка в {config.content_path.name}: {e}")

    db = Database(config.db_path)
    await db.connect()
    yookassa = (
        YooKassaClient(config.yookassa_shop_id, config.yookassa_secret_key)
        if config.payment_provider == "yookassa" else None
    )

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(config=config, store=store, db=db, yookassa=yookassa)
    await bot.set_my_commands(COMMANDS)

    poller = asyncio.create_task(poll_yookassa(bot, db, store, config, yookassa)) if yookassa else None
    logging.info("Бот запущен. Оплата: %s. Товаров: %d", config.payment_provider, len(store.current.products))
    try:
        await dp.start_polling(bot)
    finally:
        if poller:
            poller.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poller
        if yookassa:
            await yookassa.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
