import uuid
from dataclasses import dataclass

import aiohttp

API_URL = "https://api.yookassa.ru/v3/payments"


@dataclass(frozen=True)
class Payment:
    id: str
    status: str
    confirmation_url: str | None


class YooKassaError(Exception):
    pass


class YooKassaClient:
    def __init__(self, shop_id: str, secret_key: str):
        self._auth = aiohttp.BasicAuth(shop_id, secret_key)
        self._session: aiohttp.ClientSession | None = None

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                auth=self._auth, timeout=aiohttp.ClientTimeout(total=20)
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def create_payment(self, amount_rub: int, description: str,
                             order_id: int, return_url: str) -> Payment:
        body = {
            "amount": {"value": f"{amount_rub}.00", "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description[:128],
            "metadata": {"order_id": str(order_id)},
        }
        headers = {"Idempotence-Key": str(uuid.uuid4())}
        async with self._http().post(API_URL, json=body, headers=headers) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise YooKassaError(f"{resp.status}: {data.get('description', data)}")
        return self._payment(data)

    async def get_payment(self, payment_id: str) -> Payment:
        async with self._http().get(f"{API_URL}/{payment_id}") as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise YooKassaError(f"{resp.status}: {data.get('description', data)}")
        return self._payment(data)

    @staticmethod
    def _payment(data: dict) -> Payment:
        return Payment(
            id=data["id"],
            status=data["status"],
            confirmation_url=(data.get("confirmation") or {}).get("confirmation_url"),
        )
