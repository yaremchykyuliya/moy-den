import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

PROVIDERS = {"stars", "yookassa"}


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]
    payment_provider: str
    yookassa_shop_id: str
    yookassa_secret_key: str
    db_path: Path
    content_path: Path


def _admin_ids(raw: str) -> frozenset[int]:
    try:
        return frozenset(int(part) for part in raw.replace(" ", "").split(",") if part)
    except ValueError:
        raise SystemExit("ADMIN_IDS: укажи числовые Telegram ID через запятую")


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задан BOT_TOKEN в файле .env")

    provider = os.getenv("PAYMENT_PROVIDER", "stars").strip().lower()
    if provider not in PROVIDERS:
        raise SystemExit("PAYMENT_PROVIDER должен быть stars или yookassa")

    shop_id = os.getenv("YOOKASSA_SHOP_ID", "").strip()
    secret = os.getenv("YOOKASSA_SECRET_KEY", "").strip()
    if provider == "yookassa" and not (shop_id and secret):
        raise SystemExit("Для ЮKassa заполни YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY")

    return Config(
        bot_token=token,
        admin_ids=_admin_ids(os.getenv("ADMIN_IDS", "")),
        payment_provider=provider,
        yookassa_shop_id=shop_id,
        yookassa_secret_key=secret,
        db_path=BASE_DIR / os.getenv("DB_PATH", "shop.db"),
        content_path=BASE_DIR / os.getenv("CONTENT_PATH", "content.yaml"),
    )
