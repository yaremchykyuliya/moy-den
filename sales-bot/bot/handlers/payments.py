import html
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .. import keyboards as kb
from ..config import Config
from ..content import ContentStore, Product
from ..db import Database
from ..sales import buyer_name, check_yookassa_order, complete_order, deliver
from ..yookassa import YooKassaClient, YooKassaError

log = logging.getLogger(__name__)
router = Router(name="payments")


def _order_id(payload: str) -> int | None:
    prefix, _, value = payload.partition(":")
    return int(value) if prefix == "order" and value.isdigit() else None


async def _paid_product(callback: CallbackQuery, product_id: str, store: ContentStore) -> Product | None:
    product = store.product(product_id)
    if product is None or product.free:
        await callback.answer("Этого продукта уже нет в продаже", show_alert=True)
        return None
    return product


@router.callback_query(kb.BuyCb.filter())
async def buy(callback: CallbackQuery, callback_data: kb.BuyCb, bot: Bot, config: Config,
              store: ContentStore, db: Database, yookassa: YooKassaClient | None):
    product = await _paid_product(callback, callback_data.id, store)
    if product is None:
        return
    if await db.has_paid(callback.from_user.id, product.id):
        await callback.answer()
        await callback.message.answer(store.text("already_bought"))
        await deliver(bot, callback.from_user.id, product)
        return

    await callback.answer()
    if len(config.payment_methods) == 1:
        await _start_payment(callback, product, config.payment_methods[0], bot, config, store, db, yookassa)
        return
    await callback.message.answer(
        store.text("pay_choose", product=html.escape(product.title)),
        reply_markup=kb.pay_methods(product, config.payment_methods),
    )


@router.callback_query(kb.PayCb.filter())
async def pay(callback: CallbackQuery, callback_data: kb.PayCb, bot: Bot, config: Config,
              store: ContentStore, db: Database, yookassa: YooKassaClient | None):
    product = await _paid_product(callback, callback_data.id, store)
    if product is None or callback_data.method not in config.payment_methods:
        return
    await callback.answer()
    await _start_payment(callback, product, callback_data.method, bot, config, store, db, yookassa)


async def _start_payment(callback: CallbackQuery, product: Product, method: str, bot: Bot,
                         config: Config, store: ContentStore, db: Database,
                         yookassa: YooKassaClient | None) -> None:
    user_id = callback.from_user.id
    title = html.escape(product.title)

    if method == "tribute":
        await callback.message.answer(
            store.text("tribute_prompt", product=title, amount=product.price_rub),
            reply_markup=kb.url_button("💳 Оплатить в Tribute", product.tribute_url),
        )
        return

    currency = "XTR" if method == "stars" else "RUB"
    amount = product.price(method)
    order_id = await db.create_order(user_id, product.id, amount, currency, method)

    if method == "transfer":
        await callback.message.answer(
            store.text("transfer_prompt", product=title, amount=amount, order=order_id,
                       details=html.escape(config.transfer_details)),
            reply_markup=kb.transfer_cancel(order_id),
        )
        return

    if method == "stars":
        await callback.message.answer_invoice(
            title=product.title[:32],
            description=store.text("pay_prompt")[:255],
            payload=f"order:{order_id}",
            currency="XTR",
            prices=[LabeledPrice(label=product.title[:32], amount=amount)],
        )
        return

    me = await bot.get_me()
    try:
        payment = await yookassa.create_payment(
            amount_rub=amount,
            description=f"{product.title} (заказ №{order_id})",
            order_id=order_id,
            return_url=f"https://t.me/{me.username}",
        )
    except YooKassaError as e:
        log.error("ЮKassa не создала платёж для заказа %s: %s", order_id, e)
        await db.set_status(order_id, "failed")
        await callback.message.answer(store.text("delivery_error"))
        return
    await db.set_payment_id(order_id, payment.id)
    await callback.message.answer(
        store.text("pay_prompt"), reply_markup=kb.yookassa_pay(payment.confirmation_url, order_id)
    )


# ── Перевод на карту ─────────────────────────────────────────

@router.callback_query(kb.CancelCb.filter())
async def cancel_transfer(callback: CallbackQuery, callback_data: kb.CancelCb, db: Database):
    order = await db.get_order(callback_data.order_id)
    if order is None or order.user_id != callback.from_user.id or order.status != "pending":
        await callback.answer("Этот заказ уже нельзя отменить", show_alert=True)
        return
    await db.set_status(order.id, "canceled")
    await callback.answer("Заказ отменён")
    await callback.message.edit_reply_markup(reply_markup=None)


@router.message(F.photo | F.document)
async def receipt(message: Message, bot: Bot, config: Config, store: ContentStore, db: Database):
    user_id = message.from_user.id
    order = await db.awaiting_transfer(user_id)
    if order is None:
        if user_id not in config.admin_ids:
            await message.answer(store.text("transfer_no_order"))
        return

    await db.set_status(order.id, "review")
    product = store.product(order.product_id)
    title = html.escape(product.title) if product else order.product_id
    caption = (
        f"🧾 <b>Чек по заказу №{order.id}</b>\n"
        f"{title} — <b>{order.amount} ₽</b>\n"
        f"Покупатель: {await buyer_name(bot, user_id)} (id <code>{user_id}</code>)\n\n"
        "Сверь поступление в банке и нажми кнопку.\n"
        "Чтобы отправить покупателю свой чек из «Мой налог», ответь на это сообщение файлом, фото или ссылкой."
    )
    for admin_id in config.admin_ids:
        try:
            sent = await bot.copy_message(admin_id, message.chat.id, message.message_id,
                                          caption=caption, reply_markup=kb.review(order.id))
            await db.link_admin_message(admin_id, sent.message_id, order.id)
        except Exception:
            log.exception("Не удалось переслать чек админу %s", admin_id)
    await message.answer(store.text("transfer_received", order=order.id))


# ── Звёзды Telegram ──────────────────────────────────────────

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, store: ContentStore, db: Database):
    order_id = _order_id(query.invoice_payload)
    order = await db.get_order(order_id) if order_id else None
    ok = (
        order is not None
        and order.status == "pending"
        and order.user_id == query.from_user.id
        and order.amount == query.total_amount
        and order.currency == query.currency
        and (product := store.product(order.product_id)) is not None
        and not product.free
    )
    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Этот счёт устарел. Открой продукт в меню заново.")


@router.message(F.successful_payment)
async def successful_payment(message: Message, bot: Bot, config: Config,
                             store: ContentStore, db: Database):
    payment = message.successful_payment
    order_id = _order_id(payment.invoice_payload)
    order = await db.get_order(order_id) if order_id else None
    if order is None:
        log.error("Оплата без заказа: %s", payment.invoice_payload)
        return
    await complete_order(bot, db, store, config, order, payment.telegram_payment_charge_id)


# ── ЮKassa ───────────────────────────────────────────────────

@router.callback_query(kb.CheckCb.filter())
async def check_payment(callback: CallbackQuery, callback_data: kb.CheckCb, bot: Bot,
                        config: Config, store: ContentStore, db: Database,
                        yookassa: YooKassaClient | None):
    order = await db.get_order(callback_data.order_id)
    if order is None or order.user_id != callback.from_user.id or yookassa is None:
        await callback.answer("Не нашёл этот заказ", show_alert=True)
        return
    if order.status == "paid":
        await callback.answer("Этот заказ уже оплачен — продукт в «Моих покупках»", show_alert=True)
        return
    if order.status != "pending":
        await callback.answer(store.text("pay_canceled"), show_alert=True)
        return

    try:
        status = await check_yookassa_order(bot, db, store, config, yookassa, order)
    except YooKassaError as e:
        log.warning("ЮKassa, заказ %s: %s", order.id, e)
        status = "pending"

    if status == "succeeded":
        await callback.answer()
    elif status == "canceled":
        await callback.answer(store.text("pay_canceled"), show_alert=True)
    else:
        await callback.answer(store.text("pay_waiting"), show_alert=True)
