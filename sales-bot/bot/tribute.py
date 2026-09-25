"""Приём уведомлений об оплате от Tribute (вебхуки).

Tribute шлёт POST с JSON {"name": ..., "payload": {...}} и подписью в заголовке trbt-signature —
HMAC-SHA256 от тела запроса, ключ — API-ключ из кабинета Tribute.
Продукт покупателю выдаёт сам Tribute; вебхук нужен, чтобы бот узнал о покупке:
«Мои покупки», статистика, уведомление автору, прогрев не предлагает купленное.
"""
import base64
import hashlib
import hmac
import html
import json
import logging

from aiogram import Bot
from aiohttp import web

from .config import Config
from .content import ContentStore
from .db import Database
from .sales import complete_order, notify_admins

log = logging.getLogger(__name__)
PROVIDER = "tribute"


def verify_signature(api_key: str, body: bytes, signature: str) -> bool:
    if not api_key or not signature:
        return False
    supplied = signature.strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied.split("=", 1)[1].strip()
    digest = hmac.new(api_key.encode(), body, hashlib.sha256).digest()
    return (hmac.compare_digest(supplied.lower(), digest.hex())
            or hmac.compare_digest(supplied, base64.b64encode(digest).decode()))


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def on_purchase(payload: dict, bot: Bot, db: Database, store: ContentStore, config: Config) -> None:
    product_id = _int(payload.get("product_id"))
    purchase_id = _int(payload.get("purchase_id"))
    user_id = _int(payload.get("telegram_user_id"))
    product = store.product_by_tribute_id(product_id) if product_id is not None else None
    name = html.escape(str(payload.get("product_name") or product_id))

    if product is None or purchase_id is None or user_id is None:
        await notify_admins(
            bot, config,
            f"💰 Оплата в Tribute: «{name}», покупка {purchase_id}.\n"
            "Бот не смог сопоставить её с продуктом или покупателем — проверь tribute_product_id в content.yaml. "
            "Продукт покупателю выдал Tribute.",
        )
        return

    currency = str(payload.get("currency") or "rub").upper()
    amount = (_int(payload.get("amount")) or 0) // 100
    payment_id = str(purchase_id)
    order_id = await db.create_order(user_id, product.id, amount, currency, PROVIDER, payment_id)
    if order_id is None:
        return  # повторное уведомление — уже учли
    if not await db.user_exists(user_id):
        # Бот не может первым написать тому, кто его не запускал
        await db.mark_paid(order_id, payment_id)
        await notify_admins(
            bot, config,
            f"💰 Новая покупка через Tribute №{order_id}: {html.escape(product.title)} — {amount} {currency}.\n"
            "Покупатель не запускал этого бота, поэтому продукт ему выдал только Tribute.",
        )
        return
    await complete_order(bot, db, store, config, await db.get_order(order_id), payment_id)


async def on_refund(payload: dict, bot: Bot, db: Database, config: Config) -> None:
    purchase_id = _int(payload.get("purchase_id"))
    order = await db.get_order_by_payment_id(PROVIDER, str(purchase_id)) if purchase_id is not None else None
    if order is None or order.status == "refunded":
        return
    await db.set_status(order.id, "refunded")
    await notify_admins(bot, config, f"↩️ Возврат в Tribute по заказу №{order.id} (покупка {purchase_id}).")


def make_app(bot: Bot, db: Database, store: ContentStore, config: Config) -> web.Application:
    async def handle(request: web.Request) -> web.Response:
        body = await request.read()
        if not verify_signature(config.tribute_api_key, body, request.headers.get("trbt-signature", "")):
            log.warning("Tribute: запрос с неверной подписью отклонён")
            return web.Response(status=401, text="bad signature")
        try:
            data = json.loads(body)
        except ValueError:
            return web.Response(status=400, text="bad json")

        event = data.get("name")
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        if event == "new_digital_product":
            await on_purchase(payload, bot, db, store, config)
        elif event == "digital_product_refunded":
            await on_refund(payload, bot, db, config)
        else:
            log.info("Tribute: событие %s пропущено", event)
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_post(config.tribute_webhook_path, handle)
    return app


async def start_server(bot: Bot, db: Database, store: ContentStore, config: Config) -> web.AppRunner:
    runner = web.AppRunner(make_app(bot, db, store, config))
    await runner.setup()
    await web.TCPSite(runner, config.tribute_webhook_host, config.tribute_webhook_port).start()
    log.info("Tribute: жду уведомления на %s:%s%s", config.tribute_webhook_host,
             config.tribute_webhook_port, config.tribute_webhook_path)
    return runner
