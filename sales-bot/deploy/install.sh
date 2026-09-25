#!/usr/bin/env bash
# Установка бота на VPS с Ubuntu 22.04 / 24.04. Запуск: sudo bash install.sh
set -euo pipefail

REPO="${REPO:-https://github.com/yaremchykyuliya/moy-den.git}"
BRANCH="${BRANCH:-main}"
ROOT=/opt/moy-den
BOT="$ROOT/sales-bot"

[ "$(id -u)" -eq 0 ] || { echo "Запусти через sudo: sudo bash install.sh"; exit 1; }

echo "→ Ставлю системные пакеты"
apt-get update -qq
apt-get install -y -qq git python3 python3-venv sqlite3 >/dev/null

echo "→ Создаю пользователя salesbot"
id salesbot >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin salesbot

echo "→ Скачиваю код (ветка $BRANCH)"
if [ -d "$ROOT/.git" ]; then
  git -C "$ROOT" fetch -q origin "$BRANCH" && git -C "$ROOT" checkout -q "$BRANCH" && git -C "$ROOT" pull -q --ff-only origin "$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO" "$ROOT"
fi

echo "→ Ставлю зависимости Python"
python3 -m venv "$BOT/.venv"
"$BOT/.venv/bin/pip" install -q --upgrade pip
"$BOT/.venv/bin/pip" install -q -r "$BOT/requirements.txt"

mkdir -p "$BOT/products/paid" "$BOT/backups"
if [ ! -f "$BOT/.env" ]; then
  cp "$BOT/.env.example" "$BOT/.env"
  NEED_ENV=1
fi
chown -R salesbot:salesbot "$ROOT"
chmod 600 "$BOT/.env"

echo "→ Настраиваю автозапуск и ночные копии базы"
install -m 644 "$BOT/deploy/sales-bot.service" /etc/systemd/system/sales-bot.service
cat > /etc/cron.d/sales-bot-backup <<CRON
30 3 * * * salesbot $BOT/deploy/backup.sh
CRON
systemctl daemon-reload
systemctl enable -q sales-bot

if [ "${NEED_ENV:-0}" = 1 ]; then
  echo
  echo "Почти готово. Осталось:"
  echo "  1. Заполни настройки:   sudo nano $BOT/.env"
  echo "  2. Загрузи платные PDF в $BOT/products/paid/"
  echo "  3. Запусти бота:        sudo systemctl start sales-bot"
  exit 0
fi

systemctl restart sales-bot
sleep 3
systemctl --no-pager --lines=5 status sales-bot || true
echo
echo "Готово. Логи бота: sudo journalctl -u sales-bot -f"
