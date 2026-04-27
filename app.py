"""
Spartak Ticket Tracker с Telegram интеграцией
Использует Playwright для рендеринга JavaScript контента
"""

import threading
import time
import logging
from datetime import datetime
import os
from pathlib import Path

from flask import Flask, jsonify, render_template
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ─── Настройки ───────────────────────────────────────────────────────────────

TARGET_URL = (
    "https://tickets.spartak.com/matches"
    "?team=94974f94-27da-4350-81b3-9eb7afa82237"
)
KEYWORD = "ЦСКА"
CHECK_INTERVAL = 120  # секунды между проверками

# ─── Telegram настройки ──────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("8693315272:AAF1Hopx2a8ofPZ6jVFSVP2RJpDllnfBXcE", "")
TELEGRAM_CHANNEL_ID = os.getenv("-1001678361233", "")

# ─── Логирование ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Отключаем verbose логи Werkzeug (Flask HTTP requests)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# ─── Состояние приложения ────────────────────────────────────────────────────

state = {
    "tickets_found": False,
    "last_check": None,
    "last_status": "init",
    "error_msg": None,
    "check_count": 0,
    "telegram_sent": False,
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

    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        log.info("✅ Сообщение отправлено в Telegram")
        return True
    except Exception as exc:
        log.error("❌ Ошибка при отправке в Telegram: %s", exc)
        return False


# ─── Мониторинг с Playwright ────────────────────────────────────────────────

def check_tickets() -> bool:
    """
    Загружает страницу Спартака с помощью Playwright (рендерит JavaScript).
    Ищет ключевое слово в полностью загруженной странице.
    Возвращает True если слово найдено, иначе False.
    """
    try:
        with sync_playwright() as p:
            # Запускаем браузер в headless режиме
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Устанавливаем user-agent
            page.set_extra_http_headers({
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                )
            })
            
            # Загружаем страницу (ждём загрузки всех ресурсов)
            log.info("🔄 Загружаю страницу Спартака...")
            page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
            
            # Даём странице ещё 3 секунды на рендеринг
            page.wait_for_timeout(3000)
            
            # Получаем весь текст со страницы
            page_text = page.content()
            
            browser.close()
            
            # Ищем ключевое слово (без учёта регистра)
            found = KEYWORD.upper() in page_text.upper()
            
            return found
    
    except PlaywrightTimeoutError:
        log.error("❌ Timeout при загрузке страницы (более 60 сек)")
        raise
    except Exception as exc:
        log.error("❌ Ошибка при загрузке страницы: %s", exc)
        raise


def monitor_loop():
    """Фоновый поток: бесконечный цикл проверки билетов."""
    log.info("═" * 70)
    log.info("🎫 СПАРТАК ТРЕКЕР ЗАПУЩЕН")
    log.info("─" * 70)
    log.info("Интервал проверки: %d сек", CHECK_INTERVAL)
    log.info("Ключевое слово: «%s»", KEYWORD)
    log.info("Способ загрузки: Playwright (с рендерингом JavaScript)")
    
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID:
        log.info("✅ Telegram интеграция: АКТИВИРОВАНА")
    else:
        log.warning("⚠️  Telegram интеграция: НЕ НАСТРОЕНА")
    
    log.info("═" * 70)

    while True:
        now_iso = datetime.now().isoformat(timespec="seconds")
        try:
            log.info("🔍 Проверка #%d...", state["check_count"] + 1)
            found = check_tickets()
            
            with state_lock:
                state["tickets_found"] = found
                state["last_check"] = now_iso
                state["last_status"] = "found" if found else "not_found"
                state["error_msg"] = None
                state["check_count"] += 1

                # Если билеты найдены и ещё не отправили — отправляем
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
                log.warning("🔴 БИЛЕТЫ НАЙДЕНЫ! «%s» обнаружено на странице!", KEYWORD)
            else:
                log.info("⚪ Билеты не найдены")

        except Exception as exc:
            with state_lock:
                state["last_check"] = now_iso
                state["last_status"] = "error"
                state["error_msg"] = str(exc)
                state["check_count"] += 1
            log.error("❌ Ошибка: %s", exc)

        log.info("⏳ Следующая проверка через %d сек...\n", CHECK_INTERVAL)
        time.sleep(CHECK_INTERVAL)


# ─── Инициализация Playwright ───────────────────────────────────────────────

def install_playwright():
    """Устанавливает браузер для Playwright (требуется один раз)."""
    try:
        # Проверяем, установлен ли браузер
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        log.info("✅ Playwright браузер уже установлен")
    except Exception:
        log.warning("⚠️  Устанавливаю Playwright браузер...")
        os.system("playwright install chromium")
        log.info("✅ Playwright браузер установлен")


# ─── Точка входа ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Устанавливаем браузер, если нужно
    install_playwright()
    
    # Запускаем фоновый поток мониторинга
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    log.info("🚀 Flask-сервер стартует на http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
