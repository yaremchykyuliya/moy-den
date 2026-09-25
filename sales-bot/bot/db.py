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
CREATE TABLE IF NOT EXISTS claims (
    user_id     INTEGER NOT NULL,
    product_id  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, product_id)
);
CREATE TABLE IF NOT EXISTS nurture_sent (
    user_id     INTEGER NOT NULL,
    step_id     TEXT NOT NULL,
    sent_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, step_id)
);
CREATE TABLE IF NOT EXISTS admin_messages (
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    order_id    INTEGER NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_payment ON orders(provider, provider_payment_id)
    WHERE provider_payment_id IS NOT NULL;
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
        async with self._conn.execute("PRAGMA table_info(users)") as cur:
            columns = {row["name"] for row in await cur.fetchall()}
        if "blocked" not in columns:
            await self._conn.execute("ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    async def upsert_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        await self.conn.execute(
            """INSERT INTO users (id, username, first_name) VALUES (?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET username = excluded.username,
                                             first_name = excluded.first_name,
                                             blocked = 0""",
            (user_id, username, first_name),
        )
        await self.conn.commit()

    async def create_order(self, user_id: int, product_id: str, amount: int,
                           currency: str, provider: str, payment_id: str | None = None) -> int | None:
        """None — заказ с таким payment_id уже есть (повторное уведомление платёжки)."""
        try:
            cur = await self.conn.execute(
                """INSERT INTO orders (user_id, product_id, amount, currency, provider, provider_payment_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, product_id, amount, currency, provider, payment_id),
            )
        except aiosqlite.IntegrityError:
            return None
        await self.conn.commit()
        return cur.lastrowid

    async def get_order_by_payment_id(self, provider: str, payment_id: str) -> Order | None:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE provider = ? AND provider_payment_id = ?", (provider, payment_id)
        ) as cur:
            row = await cur.fetchone()
        return self._order(row) if row else None

    async def awaiting_transfer(self, user_id: int) -> Order | None:
        """Последний заказ «перевод на карту», по которому человек ещё не прислал чек."""
        async with self.conn.execute(
            """SELECT * FROM orders WHERE user_id = ? AND provider = 'transfer' AND status = 'pending'
                 AND created_at >= datetime('now', '-3 days')
               ORDER BY id DESC LIMIT 1""",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        return self._order(row) if row else None

    async def link_admin_message(self, chat_id: int, message_id: int, order_id: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO admin_messages (chat_id, message_id, order_id) VALUES (?, ?, ?)",
            (chat_id, message_id, order_id),
        )
        await self.conn.commit()

    async def order_for_admin_message(self, chat_id: int, message_id: int) -> Order | None:
        async with self.conn.execute(
            """SELECT o.* FROM admin_messages a JOIN orders o ON o.id = a.order_id
               WHERE a.chat_id = ? AND a.message_id = ?""",
            (chat_id, message_id),
        ) as cur:
            row = await cur.fetchone()
        return self._order(row) if row else None

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
               WHERE id = ? AND status IN ('pending', 'review')""",
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

    async def record_claim(self, user_id: int, product_id: str) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO claims (user_id, product_id) VALUES (?, ?)", (user_id, product_id)
        )
        await self.conn.commit()

    async def user_exists(self, user_id: int) -> bool:
        async with self.conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)) as cur:
            return await cur.fetchone() is not None

    async def mark_blocked(self, user_id: int) -> None:
        await self.conn.execute("UPDATE users SET blocked = 1 WHERE id = ?", (user_id,))
        await self.conn.commit()

    async def audience(self, segment: str) -> list[int]:
        """all — все, no_purchase — ни разу не купили, buyers — купили хотя бы раз."""
        paid = "SELECT user_id FROM orders WHERE status = 'paid'"
        where = {"all": "", "no_purchase": f"AND id NOT IN ({paid})", "buyers": f"AND id IN ({paid})"}[segment]
        async with self.conn.execute(f"SELECT id FROM users WHERE blocked = 0 {where} ORDER BY id") as cur:
            return [r["id"] for r in await cur.fetchall()]

    async def nurture_due(self, step_id: str, delay_minutes: int, window_minutes: int,
                          skip_if_bought: tuple[str, ...]) -> list[int]:
        """Кому пора отправить шаг прогрева: отсчёт от первого бесплатного гайда.

        Окно не даёт отправить шаг тем, кто забрал гайд давно — например, если шаг добавили позже.
        """
        skip = ""
        if skip_if_bought:
            marks = ",".join("?" * len(skip_if_bought))
            skip = f"""AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id = c.user_id
                       AND o.status = 'paid' AND o.product_id IN ({marks}))"""
        query = f"""
            SELECT c.user_id FROM (SELECT user_id, MIN(created_at) AS first_at FROM claims GROUP BY user_id) c
            JOIN users u ON u.id = c.user_id AND u.blocked = 0
            WHERE c.first_at <= datetime('now', ?) AND c.first_at > datetime('now', ?)
              AND NOT EXISTS (SELECT 1 FROM nurture_sent n WHERE n.user_id = c.user_id AND n.step_id = ?)
              {skip}"""
        params = (f"-{delay_minutes} minutes", f"-{delay_minutes + window_minutes} minutes", step_id,
                  *skip_if_bought)
        async with self.conn.execute(query, params) as cur:
            return [r["user_id"] for r in await cur.fetchall()]

    async def mark_nurture_sent(self, user_id: int, step_id: str) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO nurture_sent (user_id, step_id) VALUES (?, ?)", (user_id, step_id)
        )
        await self.conn.commit()

    async def stats(self) -> dict:
        async with self.conn.execute("SELECT COUNT(*), SUM(blocked) FROM users") as cur:
            users, blocked = await cur.fetchone()
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
        async with self.conn.execute(
            """SELECT product_id, COUNT(*) AS people FROM claims
               GROUP BY product_id ORDER BY people DESC"""
        ) as cur:
            claims = [dict(r) for r in await cur.fetchall()]
        async with self.conn.execute(
            "SELECT step_id, COUNT(*) AS people FROM nurture_sent GROUP BY step_id ORDER BY step_id"
        ) as cur:
            nurture = [dict(r) for r in await cur.fetchall()]
        async with self.conn.execute("SELECT COUNT(*) FROM orders WHERE status = 'review'") as cur:
            review = (await cur.fetchone())[0]
        return {"users": users, "blocked": blocked or 0, "review": review, "buyers": buyers, "by_product": by_product,
                "claims": claims, "nurture": nurture}

    @staticmethod
    def _order(row: aiosqlite.Row) -> Order:
        return Order(**{k: row[k] for k in Order.__dataclass_fields__})
