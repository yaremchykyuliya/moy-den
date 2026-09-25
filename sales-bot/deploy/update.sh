#!/usr/bin/env bash
# Обновить бота до свежей версии из GitHub. Запуск: sudo bash /opt/moy-den/sales-bot/deploy/update.sh
set -euo pipefail
ROOT=/opt/moy-den
BOT="$ROOT/sales-bot"
BRANCH="${BRANCH:-main}"

sudo -u salesbot "$BOT/deploy/backup.sh"
sudo -u salesbot git -C "$ROOT" pull -q --ff-only origin "$BRANCH"
"$BOT/.venv/bin/pip" install -q -r "$BOT/requirements.txt"
systemctl restart sales-bot
sleep 3
systemctl --no-pager --lines=5 status sales-bot || true
