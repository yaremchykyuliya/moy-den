import html

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import Message

from ..config import Config
from ..content import ContentError, ContentStore
from ..db import Database
from ..sales import CURRENCY_LABEL

router = Router(name="admin")


class IsAdmin(Filter):
    async def __call__(self, message: Message, config: Config) -> bool:
        return message.from_user is not None and message.from_user.id in config.admin_ids


router.message.filter(IsAdmin())


@router.message(Command("admin"))
async def help_(message: Message):
    await message.answer(
        "<b>Команды администратора</b>\n\n"
        "/stats — пользователи, покупатели, выручка\n"
        "/reload — перечитать content.yaml без перезапуска\n"
        "/refund &lt;номер заказа&gt; — вернуть звёзды (только для Stars)"
    )


@router.message(Command("stats"))
async def stats(message: Message, db: Database, store: ContentStore):
    s = await db.stats()
    lines = [
        "<b>Статистика</b>\n",
        f"Запустили бота: <b>{s['users']}</b>",
        f"Купили хотя бы раз: <b>{s['buyers']}</b>",
    ]
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
