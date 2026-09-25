import asyncio
import html
import logging
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, Filter
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import Config
from ..content import ContentError, ContentStore
from ..db import Database
from ..keyboards import ProductCb, ReviewCb, ScreenCb
from ..sales import CURRENCY_LABEL, complete_order

log = logging.getLogger(__name__)
router = Router(name="admin")

SEGMENTS = {"all": "Всем", "no_purchase": "Кто не купил", "buyers": "Кто купил"}
SEND_INTERVAL = 0.05  # ~20 сообщений в секунду — ниже лимита Telegram


class IsAdmin(Filter):
    async def __call__(self, event: Message | CallbackQuery, config: Config) -> bool:
        return event.from_user is not None and event.from_user.id in config.admin_ids


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class BroadcastCb(CallbackData, prefix="bc"):
    segment: str


@dataclass
class Draft:
    chat_id: int
    message_id: int
    markup: InlineKeyboardMarkup | None


_drafts: dict[int, Draft] = {}
_running: set[asyncio.Task] = set()


@router.message(Command("admin"))
async def help_(message: Message):
    await message.answer(
        "<b>Команды администратора</b>\n\n"
        "/stats — пользователи, покупатели, выручка\n"
        "/reload — перечитать content.yaml без перезапуска\n"
        "/refund &lt;номер заказа&gt; — вернуть звёзды (только для Stars)\n\n"
        "<b>Рассылка</b>\n"
        "1. Напиши боту сообщение: текст, фото, видео — как обычно.\n"
        "2. Ответь на него командой /broadcast.\n"
        "   /broadcast guide — добавит кнопку на продукт или экран с этим id.\n"
        "3. Проверь превью и выбери, кому отправить.\n\n"
        "<b>Переводы на карту</b>\n"
        "Чек покупателя придёт сюда с кнопками «выдать / отклонить».\n"
        "Ответь на него своим чеком из «Мой налог» — бот перешлёт покупателю."
    )


@router.message(Command("stats"))
async def stats(message: Message, db: Database, store: ContentStore):
    s = await db.stats()
    lines = [
        "<b>Статистика</b>\n",
        f"Запустили бота: <b>{s['users']}</b> (заблокировали: {s['blocked']})",
        f"Купили хотя бы раз: <b>{s['buyers']}</b>",
    ]
    if s["review"]:
        lines.append(f"🧾 Переводов ждут проверки: <b>{s['review']}</b>")
    if s["by_product"]:
        lines.append("\n<b>Продажи</b>")
        for row in s["by_product"]:
            product = store.product(row["product_id"])
            title = html.escape(product.title) if product else row["product_id"]
            cur = CURRENCY_LABEL.get(row["currency"], row["currency"])
            lines.append(f"• {title}: {row['sales']} шт. — {row['revenue']} {cur}")
    if s["claims"]:
        lines.append("\n<b>Забрали бесплатно</b>")
        for row in s["claims"]:
            product = store.product(row["product_id"])
            title = html.escape(product.title) if product else row["product_id"]
            lines.append(f"• {title}: {row['people']} чел.")
    if s["nurture"]:
        lines.append("\n<b>Прогрев отправлен</b>")
        for row in s["nurture"]:
            lines.append(f"• {html.escape(row['step_id'])}: {row['people']} чел.")
    await message.answer("\n".join(lines))


@router.message(Command("reload"))
async def reload(message: Message, store: ContentStore):
    try:
        content = store.reload()
    except ContentError as e:
        await message.answer(f"❌ Контент не обновлён, бот работает на старой версии.\n\n{html.escape(str(e))}")
        return
    await message.answer(
        f"✅ Контент обновлён. Экранов: {len(content.screens)}, продуктов: {len(content.products)}"
    )


@router.message(Command("refund"))
async def refund(message: Message, command: CommandObject, bot: Bot, db: Database):
    arg = (command.args or "").strip().lstrip("№")
    order = await db.get_order(int(arg)) if arg.isdigit() else None
    if order is None or order.provider != "stars" or order.status != "paid":
        await message.answer("Не нашёл оплаченный звёздами заказ с таким номером. Пример: /refund 12")
        return
    await bot.refund_star_payment(
        user_id=order.user_id, telegram_payment_charge_id=order.provider_payment_id
    )
    await db.set_status(order.id, "refunded")
    await message.answer(f"↩️ Звёзды по заказу №{order.id} возвращены.")


def _target_button(target: str, store: ContentStore) -> InlineKeyboardMarkup | None:
    product = store.product(target)
    if product:
        data = ProductCb(id=product.id, back="start").pack()
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=product.title, callback_data=data)]])
    if store.screen(target):
        data = ScreenCb(id=target).pack()
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть", callback_data=data)]])
    return None


@router.message(Command("broadcast"))
async def broadcast(message: Message, command: CommandObject, bot: Bot, db: Database, store: ContentStore):
    source = message.reply_to_message
    if source is None:
        await message.answer("Сначала напиши сообщение для рассылки, потом ответь на него командой /broadcast.")
        return
    if _running:
        await message.answer("Предыдущая рассылка ещё идёт — дождись отчёта.")
        return

    target = (command.args or "").strip()
    markup = _target_button(target, store) if target else None
    if target and markup is None:
        await message.answer(f"Не нашёл продукт или экран с id «{html.escape(target)}».")
        return

    _drafts[message.from_user.id] = Draft(message.chat.id, source.message_id, markup)
    await message.answer("<b>Превью</b> — так увидят сообщение:")
    await bot.copy_message(message.chat.id, message.chat.id, source.message_id, reply_markup=markup)

    kb = InlineKeyboardBuilder()
    for segment, label in SEGMENTS.items():
        count = len(await db.audience(segment))
        kb.button(text=f"{label} · {count}", callback_data=BroadcastCb(segment=segment))
    kb.button(text="Отмена", callback_data=BroadcastCb(segment="cancel"))
    kb.adjust(1)
    await message.answer("Кому отправить?", reply_markup=kb.as_markup())


@router.callback_query(BroadcastCb.filter(F.segment == "cancel"))
async def broadcast_cancel(callback: CallbackQuery):
    _drafts.pop(callback.from_user.id, None)
    await callback.answer()
    await callback.message.edit_text("Рассылка отменена.")


@router.callback_query(BroadcastCb.filter())
async def broadcast_start(callback: CallbackQuery, callback_data: BroadcastCb, bot: Bot, db: Database):
    draft = _drafts.pop(callback.from_user.id, None)
    if draft is None or _running:
        await callback.answer("Черновик не найден — начни заново с /broadcast", show_alert=True)
        return
    users = await db.audience(callback_data.segment)
    await callback.answer()
    await callback.message.edit_text(f"Отправляю: {SEGMENTS[callback_data.segment].lower()}, {len(users)} чел. Пришлю отчёт.")
    task = asyncio.create_task(_send_all(bot, db, draft, users, callback.from_user.id))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _send_all(bot: Bot, db: Database, draft: Draft, users: list[int], admin_id: int) -> None:
    sent = blocked = failed = 0
    for user_id in users:
        for attempt in range(2):
            try:
                await bot.copy_message(user_id, draft.chat_id, draft.message_id, reply_markup=draft.markup)
                sent += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TelegramForbiddenError:
                await db.mark_blocked(user_id)
                blocked += 1
                break
            except Exception:
                log.exception("Рассылка: не отправилось пользователю %s", user_id)
                failed += 1
                break
        else:
            failed += 1
        await asyncio.sleep(SEND_INTERVAL)
    await bot.send_message(
        admin_id,
        f"✅ Рассылка завершена\n\nДоставлено: <b>{sent}</b>\n"
        f"Заблокировали бота: {blocked}\nОшибок: {failed}",
    )


# ── Проверка переводов на карту ──────────────────────────────

async def _mark_admin_message(callback: CallbackQuery, note: str) -> None:
    message = callback.message
    try:
        if message.caption is not None:
            await message.edit_caption(caption=f"{message.html_text}\n\n{note}", reply_markup=None)
        else:
            await message.edit_text(f"{message.html_text}\n\n{note}", reply_markup=None)
    except Exception:
        log.warning("Не удалось обновить сообщение с чеком")


@router.callback_query(ReviewCb.filter())
async def review(callback: CallbackQuery, callback_data: ReviewCb, bot: Bot, config: Config,
                 store: ContentStore, db: Database):
    order = await db.get_order(callback_data.order_id)
    if order is None or order.status not in ("pending", "review"):
        await callback.answer("Этот заказ уже обработан", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        return

    if callback_data.ok:
        await callback.answer("Выдаю продукт")
        await complete_order(bot, db, store, config, order, f"transfer:{order.id}")
        await _mark_admin_message(callback, "✅ <b>Подтверждено — продукт отправлен.</b>")
        return

    await db.set_status(order.id, "rejected")
    await callback.answer("Отклонено")
    try:
        await bot.send_message(order.user_id, store.text("transfer_rejected", order=order.id))
    except Exception:
        log.warning("Не удалось написать покупателю %s про отклонённый заказ", order.user_id)
    await _mark_admin_message(callback, "❌ <b>Отклонено — покупатель получил сообщение.</b>")


class ReplyToOrder(Filter):
    """Ответ админа на сообщение с чеком покупателя — чтобы переслать ему свой чек."""

    async def __call__(self, message: Message, db: Database) -> bool | dict:
        source = message.reply_to_message
        if source is None or (message.text or "").startswith("/"):
            return False
        order = await db.order_for_admin_message(message.chat.id, source.message_id)
        return {"order": order} if order else False


@router.message(ReplyToOrder())
async def send_seller_receipt(message: Message, order, bot: Bot, store: ContentStore):
    try:
        await bot.send_message(order.user_id, store.text("seller_receipt", order=order.id))
        await bot.copy_message(order.user_id, message.chat.id, message.message_id)
    except Exception:
        await message.answer("Не получилось отправить — возможно, покупатель заблокировал бота.")
        return
    await message.answer(f"🧾 Чек отправлен покупателю по заказу №{order.id}.")
