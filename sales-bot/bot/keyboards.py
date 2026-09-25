from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .content import Product


class MenuCb(CallbackData, prefix="m"):
    action: str


class ProductCb(CallbackData, prefix="p"):
    id: str


class BuyCb(CallbackData, prefix="b"):
    id: str


class GetCb(CallbackData, prefix="g"):
    id: str


class CheckCb(CallbackData, prefix="c"):
    order_id: int


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛍 Каталог", callback_data=MenuCb(action="catalog"))
    kb.button(text="📦 Мои покупки", callback_data=MenuCb(action="my"))
    kb.button(text="💬 Поддержка", callback_data=MenuCb(action="support"))
    kb.adjust(1, 2)
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="← В меню", callback_data=MenuCb(action="home"))
    return kb.as_markup()


def catalog(products: list[Product], provider: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"{p.title} · {p.price_label(provider)}", callback_data=ProductCb(id=p.id))
    kb.button(text="← В меню", callback_data=MenuCb(action="home"))
    kb.adjust(1)
    return kb.as_markup()


def product_card(product: Product, provider: str, owned: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if owned:
        kb.button(text="📥 Получить ещё раз", callback_data=GetCb(id=product.id))
    else:
        kb.button(text=f"Купить за {product.price_label(provider)}", callback_data=BuyCb(id=product.id))
    kb.button(text="← К каталогу", callback_data=MenuCb(action="catalog"))
    kb.adjust(1)
    return kb.as_markup()


def my_purchases(products: list[Product]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in products:
        kb.button(text=f"📥 {p.title}", callback_data=GetCb(id=p.id))
    kb.button(text="← В меню", callback_data=MenuCb(action="home"))
    kb.adjust(1)
    return kb.as_markup()


def yookassa_pay(url: str, order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Оплатить", url=url)
    kb.button(text="✅ Я оплатил(а) — проверить", callback_data=CheckCb(order_id=order_id))
    kb.adjust(1)
    return kb.as_markup()
