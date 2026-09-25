import re
from dataclasses import dataclass
from pathlib import Path

import yaml

DELIVERY_TYPES = {"file", "link", "text", "channel"}
REQUIRED_TEXTS = {
    "welcome", "catalog", "catalog_empty", "my_empty", "my_purchases", "support",
    "paysupport", "pay_prompt", "pay_waiting", "pay_canceled", "thanks",
    "already_bought", "delivery_error",
}
PRODUCT_ID = re.compile(r"^[a-z0-9_-]{1,32}$")


@dataclass(frozen=True)
class Product:
    id: str
    title: str
    description: str
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
class Content:
    texts: dict[str, str]
    products: dict[str, Product]


class ContentError(Exception):
    pass


def _positive_int(value, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContentError(f"{where}: нужна цена целым положительным числом")
    return value


def _parse_product(raw: dict, base_dir: Path, provider: str) -> Product:
    pid = str(raw.get("id", ""))
    if not PRODUCT_ID.match(pid):
        raise ContentError(
            f"id «{pid}»: только латиница в нижнем регистре, цифры, _ и -, до 32 символов"
        )
    for field in ("title", "description", "delivery"):
        if not raw.get(field):
            raise ContentError(f"Товар {pid}: не заполнено поле {field}")

    price_field = "price_stars" if provider == "stars" else "price_rub"
    _positive_int(raw.get(price_field), f"Товар {pid}, {price_field}")

    delivery = raw["delivery"]
    dtype, dvalue = delivery.get("type"), str(delivery.get("value", "")).strip()
    if dtype not in DELIVERY_TYPES:
        raise ContentError(f"Товар {pid}: delivery.type — одно из {sorted(DELIVERY_TYPES)}")
    if not dvalue:
        raise ContentError(f"Товар {pid}: не заполнено delivery.value")
    if dtype == "file":
        path = base_dir / dvalue
        if not path.is_file():
            raise ContentError(f"Товар {pid}: файл не найден — {path}")
        dvalue = str(path)
    if dtype == "channel" and not re.fullmatch(r"-100\d+", dvalue):
        raise ContentError(f"Товар {pid}: ID канала вида -100XXXXXXXXXX")

    photo = raw.get("photo")
    if photo and not str(photo).startswith(("http://", "https://")):
        path = base_dir / str(photo)
        if not path.is_file():
            raise ContentError(f"Товар {pid}: картинка не найдена — {path}")
        photo = str(path)

    return Product(
        id=pid,
        title=str(raw["title"]).strip(),
        description=str(raw["description"]).strip(),
        price_rub=raw.get("price_rub") or 0,
        price_stars=raw.get("price_stars") or 0,
        photo=photo or None,
        delivery_type=dtype,
        delivery_value=dvalue,
    )


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

    return Content(texts=texts, products=products)


class ContentStore:
    """Держит актуальный контент; /reload подменяет его без перезапуска бота."""

    def __init__(self, path: Path, provider: str):
        self.path = path
        self.provider = provider
        self.current = load_content(path, provider)

    def reload(self) -> Content:
        self.current = load_content(self.path, self.provider)
        return self.current

    def text(self, key: str, **kwargs) -> str:
        text = self.current.texts[key]
        for name, value in kwargs.items():
            text = text.replace("{" + name + "}", str(value))
        return text

    def product(self, product_id: str) -> Product | None:
        return self.current.products.get(product_id)
