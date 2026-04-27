"""
Spartak Ticket Tracker
Отслеживает появление билетов на матч ЦСКА на сайте tickets.spartak.com
"""

import threading
import time
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template

# ─── Настройки ───────────────────────────────────────────────────────────────

TARGET_URL = (
    "https://tickets.spartak.com/matches"
    "?team=94974f94-27da-4350-81b3-9eb7afa82237"
)
KEYWORD = "ЦСКА"
CHECK_INTERVAL = 45  # секунды между проверками (можно менять)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

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
    "last_check": None,       # ISO-строка последней проверки
    "last_status": "init",    # "found" | "not_found" | "error"
    "error_msg": None,
    "check_count": 0,
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


# ─── Мониторинг ──────────────────────────────────────────────────────────────

def check_tickets() -> bool:
    """
    Загружает страницу Спартака и ищет ключевое слово.
    Возвращает True, если слово найдено, иначе False.
    Бросает исключение при сетевой ошибке.
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

    log.info("Flask-сервер стартует на http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
