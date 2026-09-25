import html

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message, User

from .. import keyboards as kb
from ..content import START_SCREEN, ContentStore, Product, fill
from ..db import Database
from ..sales import deliver

router = Router(name="user")


async def _show(target: CallbackQuery | Message, text: str,
                markup: InlineKeyboardMarkup | None, photo: str | None = None) -> None:
    """Перерисовывает экран в том же сообщении, если можно; иначе шлёт новое."""
    if isinstance(target, CallbackQuery):
        message = target.message
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
        media = photo if photo.startswith("http") else FSInputFile(photo)
        await message.answer_photo(media, caption=text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


def _name(user: User) -> str:
    return html.escape(user.first_name or "")


async def _open_screen(target, screen_id: str, store: ContentStore) -> None:
    screen = store.screen(screen_id) or store.screen(START_SCREEN)
    text = fill(screen.text, name=_name(target.from_user))
    await _show(target, text, kb.screen(screen), photo=screen.photo)


async def _give_free(bot: Bot, user_id: int, product: Product, db: Database) -> None:
    await db.record_claim(user_id, product.id)
    await deliver(bot, user_id, product)


async def _open_product(target, product: Product, back_to: str, bot: Bot,
                        store: ContentStore, db: Database) -> None:
    user_id = target.from_user.id
    if product.free:
        await _give_free(bot, user_id, product, db)
        return
    owned = await db.has_paid(user_id, product.id)
    text = (
        f"<b>{html.escape(product.title)}</b>\n\n{product.description}\n\n"
        f"Стоимость: <b>{product.price_label(store.provider)}</b>"
    )
    await _show(target, text, kb.product_card(product, store.provider, owned, back_to), photo=product.photo)


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, bot: Bot,
                store: ContentStore, db: Database):
    user = message.from_user
    await db.upsert_user(user.id, user.username, user.first_name)

    arg = (command.args or "").strip()
    product = store.product(arg)
    if product:
        await _open_product(message, product, START_SCREEN, bot, store, db)
        return
    await _open_screen(message, arg if store.screen(arg) else START_SCREEN, store)


@router.message(Command("menu"))
async def menu(message: Message, store: ContentStore):
    await _open_screen(message, START_SCREEN, store)


@router.callback_query(kb.ScreenCb.filter())
async def screen(callback: CallbackQuery, callback_data: kb.ScreenCb, store: ContentStore):
    await callback.answer()
    await _open_screen(callback, callback_data.id, store)


@router.callback_query(kb.ProductCb.filter())
async def product(callback: CallbackQuery, callback_data: kb.ProductCb, bot: Bot,
                  store: ContentStore, db: Database):
    item = store.product(callback_data.id)
    if item is None:
        await callback.answer("Этого материала уже нет", show_alert=True)
        return
    await callback.answer("Отправляю 🤍" if item.free else None)
    await _open_product(callback, item, callback_data.back, bot, store, db)


@router.message(Command("my"))
@router.callback_query(kb.MyCb.filter())
async def my_purchases(event: Message | CallbackQuery, store: ContentStore, db: Database):
    if isinstance(event, CallbackQuery):
        await event.answer()
    ids = await db.paid_product_ids(event.from_user.id)
    products = [p for pid in ids if (p := store.product(pid))]
    if not products:
        await _show(event, store.text("my_empty"), kb.back())
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


@router.message(Command("paysupport"))
async def paysupport(message: Message, store: ContentStore):
    await message.answer(store.text("paysupport"))
