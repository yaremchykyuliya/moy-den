#!/usr/bin/env bash
# Обновить бота до свежей версии из GitHub. Запуск от root: bash /opt/moy-den/sales-bot/deploy/update.sh
set -euo pipefail
ROOT=/opt/moy-den
BOT="$ROOT/sales-bot"
BRANCH="${BRANCH:-main}"

[ "$(id -u)" -eq 0 ] || { echo "Запусти от root: bash update.sh (или sudo bash update.sh)"; exit 1; }
# runuser есть в любой Ubuntu, а sudo на минимальных серверах может не стоять
as_bot() { runuser -u salesbot -- "$@"; }

as_bot "$BOT/deploy/backup.sh"
as_bot git -C "$ROOT" pull -q --ff-only origin "$BRANCH"
"$BOT/.venv/bin/pip" install -q -r "$BOT/requirements.txt"
systemctl restart sales-bot
sleep 3
systemctl --no-pager --lines=5 status sales-bot || true
