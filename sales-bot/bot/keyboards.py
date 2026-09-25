from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .content import START_SCREEN, Product, Screen


class ScreenCb(CallbackData, prefix="s"):
    id: str


class MyCb(CallbackData, prefix="my"):
    pass


class ProductCb(CallbackData, prefix="p"):
    id: str
    back: str


class BuyCb(CallbackData, prefix="b"):
    id: str


class GetCb(CallbackData, prefix="g"):
    id: str


class CheckCb(CallbackData, prefix="c"):
    order_id: int


class PayCb(CallbackData, prefix="pay"):
    id: str
    method: str


class CancelCb(CallbackData, prefix="x"):
    order_id: int


class ReviewCb(CallbackData, prefix="rv"):
    order_id: int
    ok: bool


METHOD_LABELS = {
    "tribute": "💳 Картой через Tribute",
    "transfer": "🏦 Переводом на карту",
    "stars": "⭐ Звёздами Telegram",
    "yookassa": "💳 Картой или СБП",
}


def _button(text: str, kind: str, target: str, screen_id: str) -> InlineKeyboardButton:
    if kind == "url":
        return InlineKeyboardButton(text=text, url=target)
    if kind == "screen":
        data = ScreenCb(id=target)
    elif kind == "product":
        data = ProductCb(id=target, back=screen_id)
    else:
        data = MyCb()
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def screen(s: Screen) -> InlineKeyboardMarkup | None:
    rows = [[_button(b.text, b.kind, b.target, s.id) for b in row] for row in s.rows]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def back(screen_id: str = START_SCREEN, text: str = "⬅️ В меню") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=text, callback_data=ScreenCb(id=screen_id))
    return kb.as_markup()


def product_card(product: Product, methods: tuple[str, ...], owned: bool, back_to: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if owned:
        kb.button(text="📥 Получить ещё раз", callback_data=GetCb(id=product.id))
    else:
        kb.button(text=f"Купить за {product.price_label(methods)}", callback_data=BuyCb(id=product.id))
    kb.button(text="⬅️ Назад", callback_data=ScreenCb(id=back_to))
    kb.adjust(1)
    return kb.as_markup()


def my_purchases(products: list[Product]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"📥 {p.title}", callback_data=GetCb(id=p.id))
    kb.button(text="⬅️ В меню", callback_data=ScreenCb(id=START_SCREEN))
    kb.adjust(1)
    return kb.as_markup()


def yookassa_pay(url: str, order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатить", url=url)
    kb.button(text="✅ Я оплатил(а) — проверить", callback_data=CheckCb(order_id=order_id))
    kb.adjust(1)
    return kb.as_markup()


def pay_methods(product: Product, methods: tuple[str, ...]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for method in methods:
        kb.button(text=METHOD_LABELS[method], callback_data=PayCb(id=product.id, method=method))
    kb.adjust(1)
    return kb.as_markup()


def url_button(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])


def transfer_cancel(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Отменить заказ", callback_data=CancelCb(order_id=order_id))
    return kb.as_markup()


def review(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Деньги пришли — выдать", callback_data=ReviewCb(order_id=order_id, ok=True))
    kb.button(text="❌ Отклонить", callback_data=ReviewCb(order_id=order_id, ok=False))
    kb.adjust(1)
    return kb.as_markup()
