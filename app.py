"""
Spartak Ticket Tracker с Telegram интеграцией
Отслеживает появление билетов на матч ЦСКА и отправляет уведомление в Telegram
"""

import threading
import time
import logging
from datetime import datetime
import os

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template

# ─── Настройки ───────────────────────────────────────────────────────────────

TARGET_URL = (
    "https://tickets.spartak.com/matches"
    "?team=94974f94-27da-4350-81b3-9eb7afa82237"
)
KEYWORD = "ЦСКА"
CHECK_INTERVAL = 45  # секунды между проверками

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

# ─── Telegram настройки ──────────────────────────────────────────────────────
# Получи эти значения как описано выше
TELEGRAM_BOT_TOKEN = os.getenv("8693315272:AAF1Hopx2a8ofPZ6jVFSVP2RJpDllnfBXcE", "")  # Токен от BotFather
TELEGRAM_CHANNEL_ID = os.getenv("1001678361233", "")  # ID твоего канала

# Если переменные окружения не установлены, используй жёсткие значения (не рекомендуется!)
# TELEGRAM_BOT_TOKEN = "123456789:ABCdefGHIjklmnoPQRstUVwxyz"
# TELEGRAM_CHANNEL_ID = "-100123456789"

# ─── Логирование ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Состояние приложения ────────────────────────────────────────────────────

state = {
    "tickets_found": False,
    "last_check": None,
    "last_status": "init",
    "error_msg": None,
    "check_count": 0,
    "telegram_sent": False,  # Флаг: отправили ли уже сообщение в Telegram
}
state_lock = threading.Lock()

# ─── Flask ────────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/")
def index():
    """Главная страница."""
    return render_template("index.html", interval=CHECK_INTERVAL)


@app.route("/api/status")
def api_status():
    """JSON-эндпоинт: текущий статус мониторинга."""
    with state_lock:
        return jsonify(dict(state))


# ─── Telegram функции ────────────────────────────────────────────────────────

def send_telegram_message(message: str) -> bool:
    """
    Отправляет сообщение в Telegram канал.
    Возвращает True если успешно, иначе False.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        log.warning("⚠️  Telegram не настроен. Установи переменные окружения.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML",  # Позволяет использовать HTML-теги
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        log.info("✅ Сообщение отправлено в Telegram")
        return True
    except requests.RequestException as exc:
        log.error("❌ Ошибка при отправке в Telegram: %s", exc)
        return False


# ─── Мониторинг ──────────────────────────────────────────────────────────────

def check_tickets() -> bool:
    """
    Загружает страницу Спартака и ищет ключевое слово.
    Возвращает True, если слово найдено, иначе False.
    """
    response = requests.get(TARGET_URL, headers=HEADERS, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = soup.get_text(separator=" ", strip=True)

    return KEYWORD.upper() in page_text.upper()


def monitor_loop():
    """Фоновый поток: бесконечный цикл проверки билетов."""
    log.info("Мониторинг запущен. Интервал: %d сек. Ключевое слово: «%s»",
             CHECK_INTERVAL, KEYWORD)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID:
        log.info("✅ Telegram интеграция активирована")
    else:
        log.warning("⚠️  Telegram не настроен")

    while True:
        now_iso = datetime.now().isoformat(timespec="seconds")
        try:
            found = check_tickets()
            with state_lock:
                state["tickets_found"] = found
                state["last_check"] = now_iso
                state["last_status"] = "found" if found else "not_found"
                state["error_msg"] = None
                state["check_count"] += 1

                # Если билеты найдены и ещё не отправили сообщение — отправляем
                if found and not state["telegram_sent"]:
                    telegram_msg = (
                        "🎫 <b>БИЛЕТЫ ПОЯВИЛИСЬ!</b>\n\n"
                        "Поспешите: "
                        "<a href='https://tickets.spartak.com/matches"
                        "?team=94974f94-27da-4350-81b3-9eb7afa82237'>"
                        "Открыть билеты</a>"
                    )
                    if send_telegram_message(telegram_msg):
                        state["telegram_sent"] = True

            if found:
                log.warning("🔴 «%s» НАЙДЕНО! Билеты появились!", KEYWORD)
            else:
                log.info("✔ Проверка #%d — «%s» не найдено.",
                         state["check_count"], KEYWORD)

        except requests.RequestException as exc:
            with state_lock:
                state["last_check"] = now_iso
                state["last_status"] = "error"
                state["error_msg"] = str(exc)
                state["check_count"] += 1
            log.error("Ошибка при проверке: %s", exc)

        time.sleep(CHECK_INTERVAL)


# ─── Точка входа ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Запускаем фоновый поток мониторинга
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    log.info("Flask-сервер стартует")
    app.run(host="0.0.0.0", port=5000, debug=False)
