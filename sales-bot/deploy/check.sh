#!/usr/bin/env bash
# Проверка связи сервера с Telegram. Запуск: sudo bash /opt/moy-den/sales-bot/deploy/check.sh
BOT="${BOT:-/opt/moy-den/sales-bot}"
PROXY="$(grep -E '^TELEGRAM_PROXY=' "$BOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"')"

reach() {  # $1 — прокси или пусто. Любой HTTP-ответ значит, что Telegram доступен
  local code
  code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' ${1:+-x "$1"} https://api.telegram.org 2>/dev/null)
  [ -n "$code" ] && [ "$code" != "000" ]
}

echo "Проверяю связь с Telegram…"
if reach ""; then
  echo "✅ api.telegram.org открывается напрямую — прокси не нужен."
  exit 0
fi
echo "❌ Напрямую api.telegram.org не открывается."

if [ -z "$PROXY" ]; then
  echo "   Нужен прокси: впиши TELEGRAM_PROXY в $BOT/.env, перезапусти бота"
  echo "   (sudo systemctl restart sales-bot) и запусти эту проверку снова."
  exit 1
fi
if reach "$PROXY"; then
  echo "✅ Через TELEGRAM_PROXY Telegram открывается — бот будет работать через прокси."
  exit 0
fi
echo "❌ Через TELEGRAM_PROXY Telegram тоже не открывается — проверь адрес, логин и пароль прокси."
exit 1
