from dataclasses import dataclass
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,
    product_id          TEXT NOT NULL,
    amount              INTEGER NOT NULL,
    currency            TEXT NOT NULL,
    provider            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    provider_payment_id TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    paid_at             TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, provider);
"""


@dataclass(frozen=True)
class Order:
    id: int
    user_id: int
    product_id: str
    amount: int
    currency: str
    provider: str
    status: str
    provider_payment_id: str | None


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database.connect() не вызван"
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    async def upsert_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        await self.conn.execute(
            """INSERT INTO users (id, username, first_name) VALUES (?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET username = excluded.username,
                                             first_name = excluded.first_name""",
            (user_id, username, first_name),
        )
        await self.conn.commit()

    async def create_order(self, user_id: int, product_id: str, amount: int,
                           currency: str, provider: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO orders (user_id, product_id, amount, currency, provider) VALUES (?, ?, ?, ?, ?)",
            (user_id, product_id, amount, currency, provider),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def set_payment_id(self, order_id: int, payment_id: str) -> None:
        await self.conn.execute(
            "UPDATE orders SET provider_payment_id = ? WHERE id = ?", (payment_id, order_id)
        )
        await self.conn.commit()

    async def get_order(self, order_id: int) -> Order | None:
        async with self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
        return self._order(row) if row else None

    async def mark_paid(self, order_id: int, payment_id: str) -> bool:
        """True только для первого подтверждения — защита от двойной выдачи."""
        cur = await self.conn.execute(
            """UPDATE orders SET status = 'paid', paid_at = datetime('now'), provider_payment_id = ?
               WHERE id = ? AND status = 'pending'""",
            (payment_id, order_id),
        )
        await self.conn.commit()
        return cur.rowcount == 1

    async def set_status(self, order_id: int, status: str) -> None:
        await self.conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        await self.conn.commit()

    async def pending_orders(self, provider: str, max_age_hours: int) -> list[Order]:
        async with self.conn.execute(
            """SELECT * FROM orders
               WHERE status = 'pending' AND provider = ? AND provider_payment_id IS NOT NULL
                 AND created_at >= datetime('now', ?)""",
            (provider, f"-{max_age_hours} hours"),
        ) as cur:
            rows = await cur.fetchall()
        return [self._order(r) for r in rows]

    async def paid_product_ids(self, user_id: int) -> list[str]:
        async with self.conn.execute(
            """SELECT product_id FROM orders WHERE user_id = ? AND status = 'paid'
               GROUP BY product_id ORDER BY MIN(paid_at)""",
            (user_id,),
        ) as cur:
            return [r["product_id"] for r in await cur.fetchall()]

    async def has_paid(self, user_id: int, product_id: str) -> bool:
        async with self.conn.execute(
            "SELECT 1 FROM orders WHERE user_id = ? AND product_id = ? AND status = 'paid' LIMIT 1",
            (user_id, product_id),
        ) as cur:
            return await cur.fetchone() is not None

    async def stats(self) -> dict:
        async with self.conn.execute("SELECT COUNT(*) FROM users") as cur:
            users = (await cur.fetchone())[0]
        async with self.conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM orders WHERE status = 'paid'"
        ) as cur:
            buyers = (await cur.fetchone())[0]
        async with self.conn.execute(
            """SELECT product_id, currency, COUNT(*) AS sales, SUM(amount) AS revenue
               FROM orders WHERE status = 'paid' GROUP BY product_id, currency
               ORDER BY revenue DESC"""
        ) as cur:
            by_product = [dict(r) for r in await cur.fetchall()]
        return {"users": users, "buyers": buyers, "by_product": by_product}

    @staticmethod
    def _order(row: aiosqlite.Row) -> Order:
        return Order(**{k: row[k] for k in Order.__dataclass_fields__})
