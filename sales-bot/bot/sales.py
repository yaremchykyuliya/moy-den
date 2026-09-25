import asyncio
import html
import logging

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from .config import Config
from .content import ContentStore, Product
from .db import Database, Order
from .yookassa import YooKassaClient, YooKassaError

log = logging.getLogger(__name__)

CURRENCY_LABEL = {"XTR": "⭐", "RUB": "₽"}


def _open_button(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])


async def deliver(bot: Bot, user_id: int, product: Product) -> None:
    title = html.escape(product.title)
    kind, value = product.delivery_type, product.delivery_value

    if kind == "file":
        await bot.send_document(user_id, FSInputFile(value), caption=f"<b>{title}</b>")
    elif kind == "link":
        await bot.send_message(user_id, f"<b>{title}</b>", reply_markup=_open_button("Открыть", value))
    elif kind == "text":
        await bot.send_message(user_id, value)
    elif kind == "channel":
        invite = await bot.create_chat_invite_link(
            chat_id=int(value), member_limit=1, name=f"user {user_id}"[:32]
        )
        await bot.send_message(
            user_id,
            f"<b>{title}</b>\nСсылка одноразовая — она сработает только для тебя.",
            reply_markup=_open_button("Войти в канал", invite.invite_link),
        )


async def notify_admins(bot: Bot, config: Config, text: str) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            log.warning("Не удалось написать админу %s — он запускал бота?", admin_id)


async def _buyer_name(bot: Bot, user_id: int) -> str:
    try:
        chat = await bot.get_chat(user_id)
    except Exception:
        return "—"
    return f"@{chat.username}" if chat.username else html.escape(chat.full_name or "—")


async def complete_order(bot: Bot, db: Database, store: ContentStore, config: Config,
                         order: Order, payment_id: str) -> bool:
    """Отмечает заказ оплаченным и выдаёт продукт. Повторный вызов ничего не делает."""
    if not await db.mark_paid(order.id, payment_id):
        return False

    product = store.product(order.product_id)
    title = html.escape(product.title) if product else order.product_id
    buyer = await _buyer_name(bot, order.user_id)
    price = f"{order.amount} {CURRENCY_LABEL.get(order.currency, order.currency)}"

    try:
        if product is None:
            raise LookupError(f"товара {order.product_id} больше нет в content.yaml")
        await bot.send_message(order.user_id, store.text("thanks", product=title))
        await deliver(bot, order.user_id, product)
    except Exception as e:
        log.exception("Не удалось выдать заказ %s", order.id)
        await bot.send_message(order.user_id, store.text("delivery_error"))
        await notify_admins(
            bot, config,
            f"⚠️ Заказ №{order.id} ОПЛАЧЕН, но продукт не выдан.\n"
            f"{title} — {price}\nПокупатель: {buyer} (id <code>{order.user_id}</code>)\n"
            f"Ошибка: {html.escape(str(e))}",
        )
        return True

    await notify_admins(
        bot, config,
        f"💰 Новая покупка №{order.id}\n{title} — {price}\n"
        f"Покупатель: {buyer} (id <code>{order.user_id}</code>)",
    )
    return True


async def check_yookassa_order(bot: Bot, db: Database, store: ContentStore, config: Config,
                               yookassa: YooKassaClient, order: Order) -> str:
    """Возвращает статус платежа в ЮKassa: succeeded, canceled или pending."""
    payment = await yookassa.get_payment(order.provider_payment_id)
    if payment.status == "succeeded":
        await complete_order(bot, db, store, config, order, payment.id)
    elif payment.status == "canceled":
        await db.set_status(order.id, "canceled")
    return payment.status


async def poll_yookassa(bot: Bot, db: Database, store: ContentStore, config: Config,
                        yookassa: YooKassaClient, interval: int = 30) -> None:
    """Сам находит оплаченные заказы, даже если покупатель не нажал «Я оплатил»."""
    while True:
        await asyncio.sleep(interval)
        try:
            for order in await db.pending_orders("yookassa", max_age_hours=2):
                try:
                    status = await check_yookassa_order(bot, db, store, config, yookassa, order)
                except YooKassaError as e:
                    log.warning("ЮKassa, заказ %s: %s", order.id, e)
                    continue
                if status == "canceled":
                    await bot.send_message(order.user_id, store.text("pay_canceled"))
        except Exception:
            log.exception("Ошибка при проверке платежей ЮKassa")
