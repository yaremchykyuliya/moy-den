#!/usr/bin/env bash
# Копия базы покупателей и заказов. Хранит последние 14 копий.
set -euo pipefail
BOT="${BOT:-/opt/moy-den/sales-bot}"
[ -f "$BOT/shop.db" ] || exit 0
mkdir -p "$BOT/backups"
sqlite3 "$BOT/shop.db" ".backup '$BOT/backups/shop-$(date +%F).db'"
ls -1t "$BOT"/backups/shop-*.db | tail -n +15 | xargs -r rm --
