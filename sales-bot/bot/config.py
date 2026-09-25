import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

METHODS = ("tribute", "transfer", "stars", "yookassa")
RUB_METHODS = {"tribute", "transfer", "yookassa"}


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    payment_methods: tuple[str, ...]
    db_path: Path
    content_path: Path
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/Moscow"))
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    transfer_details: str = ""
    tribute_api_key: str = ""
    tribute_webhook_host: str = "127.0.0.1"
    tribute_webhook_port: int = 8080
    tribute_webhook_path: str = "/tribute/webhook"
    telegram_proxy: str = ""


def _admin_ids(raw: str) -> frozenset[int]:
    try:
        return frozenset(int(part) for part in raw.replace(" ", "").split(",") if part)
    except ValueError:
        raise SystemExit("ADMIN_IDS: укажи числовые Telegram ID через запятую")


def _methods() -> tuple[str, ...]:
    raw = os.getenv("PAYMENT_METHODS") or os.getenv("PAYMENT_PROVIDER") or "stars"
    methods = tuple(dict.fromkeys(m.strip().lower() for m in raw.split(",") if m.strip()))
    unknown = [m for m in methods if m not in METHODS]
    if unknown or not methods:
        raise SystemExit(f"PAYMENT_METHODS: через запятую из {', '.join(METHODS)}. Непонятно: {', '.join(unknown)}")
    return methods


def _proxy(raw: str) -> str:
    raw = raw.strip()
    if raw and not raw.startswith(("http://", "https://", "socks5://", "socks4://")):
        raise SystemExit("TELEGRAM_PROXY — адрес вида socks5://логин:пароль@хост:порт или http://хост:порт")
    return raw


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задан BOT_TOKEN в файле .env")

    methods = _methods()
    admin_ids = _admin_ids(os.getenv("ADMIN_IDS", ""))

    shop_id = os.getenv("YOOKASSA_SHOP_ID", "").strip()
    secret = os.getenv("YOOKASSA_SECRET_KEY", "").strip()
    if "yookassa" in methods and not (shop_id and secret):
        raise SystemExit("Для ЮKassa заполни YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY")

    details = os.getenv("TRANSFER_DETAILS", "").strip()
    if "transfer" in methods:
        if not details:
            raise SystemExit("Для перевода на карту заполни TRANSFER_DETAILS — реквизиты для оплаты")
        if not admin_ids:
            raise SystemExit("Для перевода на карту нужен ADMIN_IDS — кто будет подтверждать оплату")

    tz_name = os.getenv("TIMEZONE", "Europe/Moscow").strip()
    try:
        timezone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise SystemExit(f"TIMEZONE: не знаю часовой пояс «{tz_name}». Пример: Europe/Moscow")

    try:
        port = int(os.getenv("TRIBUTE_WEBHOOK_PORT", "8080"))
    except ValueError:
        raise SystemExit("TRIBUTE_WEBHOOK_PORT — число, например 8080")

    return Config(
        bot_token=token,
        admin_ids=admin_ids,
        payment_methods=methods,
        db_path=BASE_DIR / os.getenv("DB_PATH", "shop.db"),
        content_path=BASE_DIR / os.getenv("CONTENT_PATH", "content.yaml"),
        timezone=timezone,
        yookassa_shop_id=shop_id,
        yookassa_secret_key=secret,
        transfer_details=details,
        tribute_api_key=os.getenv("TRIBUTE_API_KEY", "").strip(),
        tribute_webhook_host=os.getenv("TRIBUTE_WEBHOOK_HOST", "127.0.0.1").strip(),
        tribute_webhook_port=port,
        tribute_webhook_path=os.getenv("TRIBUTE_WEBHOOK_PATH", "/tribute/webhook").strip(),
        telegram_proxy=_proxy(os.getenv("TELEGRAM_PROXY", "")),
    )
