import re
from dataclasses import dataclass
from pathlib import Path

import yaml

DELIVERY_TYPES = {"file", "link", "text", "channel"}
BUTTON_KINDS = ("screen", "product", "url", "my")
REQUIRED_TEXTS = {
    "my_empty", "my_purchases", "paysupport", "pay_prompt", "pay_waiting",
    "pay_canceled", "thanks", "already_bought", "delivery_error",
}
SLUG = re.compile(r"^[a-z0-9_-]{1,28}$")
START_SCREEN = "start"


@dataclass(frozen=True)
class Product:
    id: str
    title: str
    description: str
    free: bool
    price_rub: int
    price_stars: int
    photo: str | None
    delivery_type: str
    delivery_value: str

    def price(self, provider: str) -> int:
        return self.price_stars if provider == "stars" else self.price_rub

    def price_label(self, provider: str) -> str:
        return f"{self.price_stars} ⭐" if provider == "stars" else f"{self.price_rub} ₽"


@dataclass(frozen=True)
class Button:
    text: str
    kind: str
    target: str


@dataclass(frozen=True)
class Screen:
    id: str
    text: str
    photo: str | None
    rows: tuple[tuple[Button, ...], ...]


@dataclass(frozen=True)
class Content:
    texts: dict[str, str]
    screens: dict[str, Screen]
    products: dict[str, Product]


class ContentError(Exception):
    pass


def _slug(value, where: str) -> str:
    value = str(value or "")
    if not SLUG.match(value):
        raise ContentError(
            f"{where}: id «{value}» — только латиница в нижнем регистре, цифры, _ и -, до 28 символов"
        )
    return value


def _image(photo, base_dir: Path, where: str) -> str | None:
    if not photo:
        return None
    photo = str(photo)
    if photo.startswith(("http://", "https://")):
        return photo
    path = base_dir / photo
    if not path.is_file():
        raise ContentError(f"{where}: картинка не найдена — {path}")
    return str(path)


def _parse_product(raw: dict, base_dir: Path, provider: str) -> Product:
    pid = _slug(raw.get("id"), "Товар")
    where = f"Товар {pid}"
    for field in ("title", "delivery"):
        if not raw.get(field):
            raise ContentError(f"{where}: не заполнено поле {field}")

    free = bool(raw.get("free", False))
    if not free:
        if not raw.get("description"):
            raise ContentError(f"{where}: у платного товара нужно описание (description)")
        field = "price_stars" if provider == "stars" else "price_rub"
        value = raw.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContentError(f"{where}: {field} — цена целым положительным числом (или free: true)")

    delivery = raw["delivery"]
    dtype, dvalue = delivery.get("type"), str(delivery.get("value", "")).strip()
    if dtype not in DELIVERY_TYPES:
        raise ContentError(f"{where}: delivery.type — одно из {sorted(DELIVERY_TYPES)}")
    if not dvalue:
        raise ContentError(f"{where}: не заполнено delivery.value")
    if dtype == "file":
        path = base_dir / dvalue
        if not path.is_file():
            raise ContentError(f"{where}: файл не найден — {path}")
        dvalue = str(path)
    if dtype == "channel" and not re.fullmatch(r"-100\d+", dvalue):
        raise ContentError(f"{where}: ID канала вида -100XXXXXXXXXX")

    return Product(
        id=pid,
        title=str(raw["title"]).strip(),
        description=str(raw.get("description") or "").strip(),
        free=free,
        price_rub=raw.get("price_rub") or 0,
        price_stars=raw.get("price_stars") or 0,
        photo=_image(raw.get("photo"), base_dir, where),
        delivery_type=dtype,
        delivery_value=dvalue,
    )


def _parse_button(raw, where: str) -> Button:
    if not isinstance(raw, dict) or not raw.get("text"):
        raise ContentError(f"{where}: у кнопки должен быть text")
    kinds = [k for k in BUTTON_KINDS if k in raw]
    if len(kinds) != 1:
        raise ContentError(
            f"{where}, кнопка «{raw['text']}»: укажи ровно одно из screen / product / url / my"
        )
    kind = kinds[0]
    target = str(raw[kind]).strip() if kind != "my" else ""
    if kind == "url" and not target.startswith(("https://", "http://", "tg://")):
        raise ContentError(f"{where}, кнопка «{raw['text']}»: url должен начинаться с https://")
    return Button(text=str(raw["text"]).strip(), kind=kind, target=target)


def _parse_screen(sid: str, raw: dict, base_dir: Path) -> Screen:
    where = f"Экран {sid}"
    if not isinstance(raw, dict) or not raw.get("text"):
        raise ContentError(f"{where}: не заполнен text")
    rows = []
    for item in raw.get("buttons") or []:
        row = item if isinstance(item, list) else [item]
        if not 1 <= len(row) <= 8:
            raise ContentError(f"{where}: в одном ряду от 1 до 8 кнопок")
        rows.append(tuple(_parse_button(b, where) for b in row))
    return Screen(
        id=sid,
        text=str(raw["text"]).strip(),
        photo=_image(raw.get("photo"), base_dir, where),
        rows=tuple(rows),
    )


def _check_links(content: Content) -> None:
    for screen in content.screens.values():
        for row in screen.rows:
            for b in row:
                if b.kind == "screen" and b.target not in content.screens:
                    raise ContentError(f"Экран {screen.id}, кнопка «{b.text}»: нет экрана «{b.target}»")
                if b.kind == "product" and b.target not in content.products:
                    raise ContentError(f"Экран {screen.id}, кнопка «{b.text}»: нет товара «{b.target}»")
    clash = content.screens.keys() & content.products.keys()
    if clash:
        raise ContentError(f"Одинаковые id у экрана и товара: {', '.join(sorted(clash))}")


def load_content(path: Path, provider: str) -> Content:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ContentError(f"Не получилось прочитать {path.name}: {e}")

    texts = {k: str(v).strip() for k, v in (data.get("texts") or {}).items()}
    missing = REQUIRED_TEXTS - texts.keys()
    if missing:
        raise ContentError(f"В texts не хватает: {', '.join(sorted(missing))}")

    products: dict[str, Product] = {}
    for raw in data.get("products") or []:
        product = _parse_product(raw, path.parent, provider)
        if product.id in products:
            raise ContentError(f"Повторяется id товара: {product.id}")
        products[product.id] = product

    screens: dict[str, Screen] = {}
    for sid, raw in (data.get("screens") or {}).items():
        sid = _slug(sid, "Экран")
        screens[sid] = _parse_screen(sid, raw, path.parent)
    if START_SCREEN not in screens:
        raise ContentError("Нужен экран start — это главное меню")

    content = Content(texts=texts, screens=screens, products=products)
    _check_links(content)
    return content


def fill(text: str, **values) -> str:
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


class ContentStore:
    """Держит актуальный контент; /reload подменяет его без перезапуска бота."""

    def __init__(self, path: Path, provider: str):
        self.path = path
        self.provider = provider
        self.current = load_content(path, provider)

    def reload(self) -> Content:
        self.current = load_content(self.path, self.provider)
        return self.current

    def text(self, key: str, **values) -> str:
        return fill(self.current.texts[key], **values)

    def product(self, product_id: str) -> Product | None:
        return self.current.products.get(product_id)

    def screen(self, screen_id: str) -> Screen | None:
        return self.current.screens.get(screen_id)
