import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .. import keyboards as kb
from ..config import Config
from ..content import ContentStore
from ..db import Database
from ..sales import check_yookassa_order, complete_order, deliver
from ..yookassa import YooKassaClient, YooKassaError

log = logging.getLogger(__name__)
router = Router(name="payments")


def _order_id(payload: str) -> int | None:
    prefix, _, value = payload.partition(":")
    return int(value) if prefix == "order" and value.isdigit() else None


@router.callback_query(kb.BuyCb.filter())
async def buy(callback: CallbackQuery, callback_data: kb.BuyCb, bot: Bot, config: Config,
              store: ContentStore, db: Database, yookassa: YooKassaClient | None):
    product = store.product(callback_data.id)
    if product is None:
        await callback.answer("Этого продукта уже нет в каталоге", show_alert=True)
        return

    user_id = callback.from_user.id
    if await db.has_paid(user_id, product.id):
        await callback.answer()
        await callback.message.answer(store.text("already_bought"))
        await deliver(bot, user_id, product)
        return

    provider = config.payment_provider
    currency = "XTR" if provider == "stars" else "RUB"
    amount = product.price(provider)
    order_id = await db.create_order(user_id, product.id, amount, currency, provider)
    await callback.answer()

    if provider == "stars":
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
        and store.product(order.product_id) is not None
    )
    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Этот счёт устарел. Открой продукт в каталоге заново.")


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
