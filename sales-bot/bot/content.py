import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DELIVERY_TYPES = {"file", "link", "text", "channel"}
BUTTON_KINDS = ("screen", "product", "flow", "url", "my")
REQUIRED_TEXTS = {
    "my_empty", "my_purchases", "paysupport", "pay_prompt", "pay_waiting",
    "pay_canceled", "thanks", "already_bought", "delivery_error",
    "pay_choose", "tribute_prompt", "transfer_prompt", "transfer_received",
    "transfer_rejected", "transfer_no_order", "seller_receipt",
    "template_hint", "template_locked",
}
RUB_METHODS = {"tribute", "transfer", "yookassa"}
TRIBUTE_URL = re.compile(r"^https://(web\.tribute\.tg|t\.me)/\S+$")
SLUG = re.compile(r"^[a-z0-9_-]{1,28}$")
START_SCREEN = "start"
CAPTION_LIMIT = 1024  # столько символов Telegram разрешает в подписи к картинке
FLOW_PLACEHOLDER = re.compile(r"\{(\d)\}")


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
    followup: "Screen | None" = None
    tribute_url: str = ""
    tribute_product_id: int | None = None
    templates_prefix: str = ""
    templates: "dict[int, dict] | None" = None

    def price(self, method: str) -> int:
        return self.price_stars if method == "stars" else self.price_rub

    def price_label(self, methods: tuple[str, ...]) -> str:
        parts = []
        if RUB_METHODS & set(methods):
            parts.append(f"{self.price_rub} ₽")
        if "stars" in methods:
            parts.append(f"{self.price_stars} ⭐")
        return " / ".join(parts)


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
class FlowOption:
    text: str   # надпись на кнопке
    value: str  # что подставится в запрос


@dataclass(frozen=True)
class FlowStep:
    text: str
    options: tuple[FlowOption, ...]


@dataclass(frozen=True)
class Flow:
    """Сценарий: пара вопросов кнопками → готовый запрос под человека → продукт."""
    id: str
    steps: tuple[FlowStep, ...]
    result_text: str
    prompt: str
    after: Screen

    def build_prompt(self, values: list[str]) -> str:
        return FLOW_PLACEHOLDER.sub(lambda m: values[int(m.group(1)) - 1], self.prompt)


@dataclass(frozen=True)
class NurtureStep:
    id: str
    delay_minutes: int
    screen: Screen
    skip_if_bought: tuple[str, ...]


@dataclass(frozen=True)
class Content:
    texts: dict[str, str]
    screens: dict[str, Screen]
    products: dict[str, Product]
    nurture: tuple[NurtureStep, ...] = ()
    nurture_hours: tuple[int, int] = (10, 21)
    flows: "dict[str, Flow]" = field(default_factory=dict)


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


def _load_templates(value, base_dir: Path, where: str) -> tuple[str, dict[int, dict] | None]:
    """Шаблоны для кнопки «Скопировать» — JSON, который собирает guides/build.py рядом с PDF."""
    if not value:
        return "", None
    path = base_dir / str(value)
    if not path.is_file():
        raise ContentError(f"{where}: файл шаблонов не найден — {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        prefix = str(data["prefix"])
        items = {int(k): {"title": str(v["title"]), "text": str(v["text"])} for k, v in data["items"].items()}
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ContentError(f"{where}: файл шаблонов повреждён — {e}")
    if not re.fullmatch(r"[a-z]{1,3}", prefix) or not items:
        raise ContentError(f"{where}: в файле шаблонов нет префикса или самих шаблонов")
    return prefix, items


def _parse_product(raw: dict, base_dir: Path, methods: tuple[str, ...]) -> Product:
    pid = _slug(raw.get("id"), "Товар")
    where = f"Товар {pid}"
    for field in ("title", "delivery"):
        if not raw.get(field):
            raise ContentError(f"{where}: не заполнено поле {field}")

    free = bool(raw.get("free", False))
    if not free:
        if not raw.get("description"):
            raise ContentError(f"{where}: у платного товара нужно описание (description)")
        needed = (["price_rub"] if RUB_METHODS & set(methods) else []) + (["price_stars"] if "stars" in methods else [])
        for field in needed:
            value = raw.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ContentError(f"{where}: {field} — цена целым положительным числом (или free: true)")
        if "tribute" in methods and not TRIBUTE_URL.match(str(raw.get("tribute_url") or "")):
            raise ContentError(f"{where}: tribute_url — ссылка на продукт в Tribute, вида https://web.tribute.tg/p/…")

    templates_prefix, templates = _load_templates(raw.get("templates"), base_dir, where)

    tribute_id = raw.get("tribute_product_id")
    if tribute_id is not None and (not isinstance(tribute_id, int) or isinstance(tribute_id, bool)):
        raise ContentError(f"{where}: tribute_product_id — число из кабинета Tribute")

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

    followup = None
    if raw.get("followup"):
        if not free:
            raise ContentError(f"{where}: followup бывает только у бесплатных продуктов")
        followup = _parse_screen(START_SCREEN, raw["followup"], base_dir, where=f"{where}, followup")

    description = str(raw.get("description") or "").strip()
    if raw.get("photo") and len(description) > CAPTION_LIMIT - 120:
        raise ContentError(f"{where}: с картинкой описание должно быть короче {CAPTION_LIMIT - 120} символов "
                           f"(сейчас {len(description)}) — так ограничивает Telegram")

    return Product(
        followup=followup,
        tribute_url=str(raw.get("tribute_url") or "").strip(),
        tribute_product_id=tribute_id,
        templates_prefix=templates_prefix,
        templates=templates,
        id=pid,
        title=str(raw["title"]).strip(),
        description=description,
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


def _parse_screen(sid: str, raw: dict, base_dir: Path, where: str | None = None) -> Screen:
    where = where or f"Экран {sid}"
    if not isinstance(raw, dict) or not raw.get("text"):
        raise ContentError(f"{where}: не заполнен text")
    rows = []
    for item in raw.get("buttons") or []:
        row = item if isinstance(item, list) else [item]
        if not 1 <= len(row) <= 8:
            raise ContentError(f"{where}: в одном ряду от 1 до 8 кнопок")
        rows.append(tuple(_parse_button(b, where) for b in row))
    text = str(raw["text"]).strip()
    if raw.get("photo") and len(text) > CAPTION_LIMIT:
        raise ContentError(f"{where}: с картинкой текст должен быть не длиннее {CAPTION_LIMIT} символов "
                           f"(сейчас {len(text)}) — так ограничивает Telegram")
    return Screen(
        id=sid,
        text=text,
        photo=_image(raw.get("photo"), base_dir, where),
        rows=tuple(rows),
    )


def _parse_flow(fid: str, raw: dict, base_dir: Path) -> Flow:
    where = f"Сценарий {fid}"
    if not isinstance(raw, dict):
        raise ContentError(f"{where}: ожидаются steps и result")
    raw_steps = raw.get("steps") or []
    if not 1 <= len(raw_steps) <= 4:
        raise ContentError(f"{where}: от 1 до 4 вопросов в steps")
    steps = []
    for i, st in enumerate(raw_steps, 1):
        options = (st or {}).get("options") or []
        if not (st or {}).get("text") or not 2 <= len(options) <= 8:
            raise ContentError(f"{where}, вопрос {i}: нужен text и от 2 до 8 вариантов в options")
        parsed = []
        for o in options:
            if isinstance(o, dict):
                label, value = str(o.get("text") or "").strip(), str(o.get("value") or "").strip()
            else:
                label = value = str(o).strip()
            if not label or not value:
                raise ContentError(f"{where}, вопрос {i}: у варианта должен быть text (и value, если указан словарём)")
            parsed.append(FlowOption(label, value))
        steps.append(FlowStep(str(st["text"]).strip(), tuple(parsed)))

    result = raw.get("result") or {}
    prompt = str(result.get("prompt") or "").strip()
    if not result.get("text") or not prompt or not result.get("after"):
        raise ContentError(f"{where}: в result нужны text, prompt и after")
    for m in FLOW_PLACEHOLDER.finditer(prompt):
        if not 1 <= int(m.group(1)) <= len(steps):
            raise ContentError(f"{where}: в prompt есть {{{m.group(1)}}}, а вопросов только {len(steps)}")
    after = _parse_screen(START_SCREEN, {"text": result["after"], "buttons": result.get("buttons")},
                          base_dir, where=f"{where}, result")
    return Flow(fid, tuple(steps), str(result["text"]).strip(), prompt, after)


DELAY = re.compile(r"^(\d+)\s*([mhd])$")
DELAY_UNITS = {"m": 1, "h": 60, "d": 1440}


def _parse_nurture(raw_steps, base_dir: Path) -> tuple[NurtureStep, ...]:
    steps, seen = [], set()
    for raw in raw_steps or []:
        sid = _slug(raw.get("id"), "Прогрев")
        if sid in seen:
            raise ContentError(f"Прогрев: повторяется id шага {sid}")
        seen.add(sid)
        match = DELAY.match(str(raw.get("after", "")).strip())
        if not match:
            raise ContentError(f"Прогрев {sid}: after — например 30m, 24h или 3d")
        skip = raw.get("skip_if_bought") or []
        skip = tuple(skip if isinstance(skip, list) else [skip])
        steps.append(NurtureStep(
            id=sid,
            delay_minutes=int(match.group(1)) * DELAY_UNITS[match.group(2)],
            screen=_parse_screen(START_SCREEN, raw, base_dir, where=f"Прогрев {sid}"),
            skip_if_bought=tuple(str(x) for x in skip),
        ))
    return tuple(sorted(steps, key=lambda st: st.delay_minutes))


def _parse_hours(raw) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", str(raw or "10-21"))
    start, end = (int(match.group(1)), int(match.group(2))) if match else (-1, -1)
    if not (0 <= start < end <= 24):
        raise ContentError("nurture_hours — например \"10-21\": с 10:00 до 21:00")
    return start, end


def _check_links(content: Content) -> None:
    holders = [(f"Экран {s.id}", s) for s in content.screens.values()]
    holders += [(f"Товар {p.id}, followup", p.followup) for p in content.products.values() if p.followup]
    holders += [(f"Прогрев {st.id}", st.screen) for st in content.nurture]
    holders += [(f"Сценарий {f.id}, result", f.after) for f in content.flows.values()]
    for st in content.nurture:
        for pid in st.skip_if_bought:
            if pid not in content.products:
                raise ContentError(f"Прогрев {st.id}: skip_if_bought — нет товара «{pid}»")
    for where, screen in holders:
        for row in screen.rows:
            for b in row:
                if b.kind == "screen" and b.target not in content.screens:
                    raise ContentError(f"{where}, кнопка «{b.text}»: нет экрана «{b.target}»")
                if b.kind == "product" and b.target not in content.products:
                    raise ContentError(f"{where}, кнопка «{b.text}»: нет товара «{b.target}»")
                if b.kind == "flow" and b.target not in content.flows:
                    raise ContentError(f"{where}, кнопка «{b.text}»: нет сценария «{b.target}»")
    clash = content.screens.keys() & content.products.keys()
    if clash:
        raise ContentError(f"Одинаковые id у экрана и товара: {', '.join(sorted(clash))}")


def load_content(path: Path, methods: tuple[str, ...]) -> Content:
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
        product = _parse_product(raw, path.parent, methods)
        if product.id in products:
            raise ContentError(f"Повторяется id товара: {product.id}")
        products[product.id] = product

    screens: dict[str, Screen] = {}
    for sid, raw in (data.get("screens") or {}).items():
        sid = _slug(sid, "Экран")
        screens[sid] = _parse_screen(sid, raw, path.parent)
    if START_SCREEN not in screens:
        raise ContentError("Нужен экран start — это главное меню")

    flows = {}
    for fid, raw in (data.get("flows") or {}).items():
        fid = _slug(fid, "Сценарий")
        flows[fid] = _parse_flow(fid, raw, path.parent)

    content = Content(
        texts=texts, screens=screens, products=products, flows=flows,
        nurture=_parse_nurture(data.get("nurture"), path.parent),
        nurture_hours=_parse_hours(data.get("nurture_hours")),
    )
    _check_links(content)
    return content


def fill(text: str, **values) -> str:
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


class ContentStore:
    """Держит актуальный контент; /reload подменяет его без перезапуска бота."""

    def __init__(self, path: Path, methods: tuple[str, ...]):
        self.path = path
        self.methods = methods
        self.current = load_content(path, methods)

    def reload(self) -> Content:
        self.current = load_content(self.path, self.methods)
        return self.current

    def text(self, key: str, **values) -> str:
        return fill(self.current.texts[key], **values)

    def product(self, product_id: str) -> Product | None:
        return self.current.products.get(product_id)

    def template(self, code: str) -> tuple[Product, int, dict] | None:
        """Шаблон по коду из ссылки «Скопировать», например p031."""
        match = re.fullmatch(r"([a-z]{1,3})(\d{3})", code)
        if not match:
            return None
        prefix, num = match.group(1), int(match.group(2))
        for product in self.current.products.values():
            if product.templates and product.templates_prefix == prefix and num in product.templates:
                return product, num, product.templates[num]
        return None

    def product_by_tribute_id(self, tribute_id: int) -> Product | None:
        return next((p for p in self.current.products.values() if p.tribute_product_id == tribute_id), None)

    def flow(self, flow_id: str) -> Flow | None:
        return self.current.flows.get(flow_id)

    def screen(self, screen_id: str) -> Screen | None:
        return self.current.screens.get(screen_id)
