import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message

from .. import keyboards as kb
from ..content import ContentStore, Product
from ..db import Database
from ..sales import deliver

router = Router(name="user")


async def _show(target: CallbackQuery | Message, text: str,
                markup: InlineKeyboardMarkup, photo: str | None = None) -> None:
    """Перерисовывает экран в том же сообщении, если можно; иначе шлёт новое."""
    if isinstance(target, CallbackQuery):
        message = target.message
        await target.answer()
        if not photo and message.text:
            await message.edit_text(text, reply_markup=markup)
            return
        try:
            await message.delete()
        except Exception:
            pass
    else:
        message = target

    if photo:
        media = FSInputFile(photo) if not photo.startswith("http") else photo
        await message.answer_photo(media, caption=text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


def _card_text(product: Product, provider: str) -> str:
    return (
        f"<b>{html.escape(product.title)}</b>\n\n{product.description}\n\n"
        f"Стоимость: <b>{product.price_label(provider)}</b>"
    )


async def _show_product(target, product: Product, store: ContentStore, db: Database) -> None:
    owned = await db.has_paid(target.from_user.id, product.id)
    await _show(
        target,
        _card_text(product, store.provider),
        kb.product_card(product, store.provider, owned),
        photo=product.photo,
    )


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, store: ContentStore, db: Database):
    user = message.from_user
    await db.upsert_user(user.id, user.username, user.first_name)

    product = store.product(command.args or "")
    if product:
        await _show_product(message, product, store, db)
        return
    name = html.escape(user.first_name or "")
    await message.answer(store.text("welcome", name=name), reply_markup=kb.main_menu())


@router.callback_query(kb.MenuCb.filter(F.action == "home"))
async def home(callback: CallbackQuery, store: ContentStore):
    name = html.escape(callback.from_user.first_name or "")
    await _show(callback, store.text("welcome", name=name), kb.main_menu())


@router.message(Command("catalog"))
@router.callback_query(kb.MenuCb.filter(F.action == "catalog"))
async def catalog(event: Message | CallbackQuery, store: ContentStore):
    products = list(store.current.products.values())
    if not products:
        await _show(event, store.text("catalog_empty"), kb.back_to_menu())
        return
    await _show(event, store.text("catalog"), kb.catalog(products, store.provider))


@router.callback_query(kb.ProductCb.filter())
async def product(callback: CallbackQuery, callback_data: kb.ProductCb,
                  store: ContentStore, db: Database):
    item = store.product(callback_data.id)
    if item is None:
        await callback.answer("Этого продукта уже нет в каталоге", show_alert=True)
        return
    await _show_product(callback, item, store, db)


@router.message(Command("my"))
@router.callback_query(kb.MenuCb.filter(F.action == "my"))
async def my_purchases(event: Message | CallbackQuery, store: ContentStore, db: Database):
    ids = await db.paid_product_ids(event.from_user.id)
    products = [p for pid in ids if (p := store.product(pid))]
    if not products:
        await _show(event, store.text("my_empty"), kb.back_to_menu())
        return
    await _show(event, store.text("my_purchases"), kb.my_purchases(products))


@router.callback_query(kb.GetCb.filter())
async def get_again(callback: CallbackQuery, callback_data: kb.GetCb, bot: Bot,
                    store: ContentStore, db: Database):
    item = store.product(callback_data.id)
    if item is None or not await db.has_paid(callback.from_user.id, callback_data.id):
        await callback.answer("Не нашёл эту покупку", show_alert=True)
        return
    await callback.answer()
    await deliver(bot, callback.from_user.id, item)


@router.message(Command("support"))
@router.callback_query(kb.MenuCb.filter(F.action == "support"))
async def support(event: Message | CallbackQuery, store: ContentStore):
    await _show(event, store.text("support"), kb.back_to_menu())


@router.message(Command("paysupport"))
async def paysupport(message: Message, store: ContentStore):
    await message.answer(store.text("paysupport"))
