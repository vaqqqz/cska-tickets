import os
import subprocess
import threading
import time
import logging
from datetime import datetime
from pathlib import Path

# ─── 1. ФОРСИРОВАННАЯ НАСТРОЙКА ОКРУЖЕНИЯ ──────────────────────────────────
# Мы добавляем пути ко всем возможным местам, где Nix хранит библиотеки
def install_and_link_libs():
    # Пути, где Railway/Nix хранят скомпилированные .so файлы
    nix_libs = [
        "/nix/var/nix/profiles/default/lib",
        "/usr/lib",
        "/usr/local/lib"
    ]
    
    # Пытаемся найти конкретные папки библиотек через системный поиск
    try:
        ld_output = subprocess.check_output(["find", "/nix/store", "-maxdepth", "2", "-name", "lib", "-type", "d"], text=True)
        nix_libs.extend(ld_output.splitlines())
    except:
        pass

    current_ld = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = ":".join(filter(None, [current_ld] + nix_libs))

install_and_link_libs()

# ─── 2. ИМПОРТЫ PLAYWRIGHT (ПОСЛЕ НАСТРОЙКИ ПУТЕЙ) ─────────────────────────
from flask import Flask, jsonify, render_template
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ─── Настройки ───────────────────────────────────────────────────────────────

TARGET_URL = "https://tickets.spartak.com/matches?team=94974f94-27da-4350-81b3-9eb7afa82237"
KEYWORD = "ЦСКА"
CHECK_INTERVAL = 120 

# Telegram (замени на переменные окружения в панели Railway для безопасности)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8693315272:AAF1Hopx2a8ofPZ6jVFSVP2RJpDllnfBXcE")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1001678361233")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

state = {
    "tickets_found": False,
    "last_check": None,
    "last_status": "init",
    "error_msg": None,
    "check_count": 0,
    "telegram_sent": False,
}
state_lock = threading.Lock()
app = Flask(__name__)

# ─── Логика ──────────────────────────────────────────────────────────────────

def send_telegram_message(message: str) -> bool:
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHANNEL_ID, "text": message, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as exc:
        log.error("❌ Telegram error: %s", exc)
        return False

def check_tickets() -> bool:
    try:
        with sync_playwright() as p:
            # КРИТИЧЕСКИЕ ФЛАГИ ДЛЯ RAILWAY
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
            context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
            page = context.new_page()
            
            log.info("🔄 Загружаю страницу...")
            page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)
            
            content = page.content()
            browser.close()
            
            return KEYWORD.upper() in content.upper()
    except Exception as exc:
        log.error("❌ Ошибка Playwright: %s", exc)
        raise

def monitor_loop():
    log.info("🎫 СПАРТАК ТРЕКЕР ЗАПУЩЕН")
    while True:
        now_iso = datetime.now().isoformat(timespec="seconds")
        try:
            log.info("🔍 Проверка #%d...", state["check_count"] + 1)
            found = check_tickets()
            
            with state_lock:
                state.update({
                    "tickets_found": found,
                    "last_check": now_iso,
                    "last_status": "found" if found else "not_found",
                    "error_msg": None,
                    "check_count": state["check_count"] + 1
                })

                if found and not state["telegram_sent"]:
                    msg = f"🎫 <b>БИЛЕТЫ НА {KEYWORD}!</b>\n<a href='{TARGET_URL}'>Купить</a>"
                    if send_telegram_message(msg):
                        state["telegram_sent"] = True
            
            if found: log.warning("🔴 НАЙДЕНО!")
        except Exception as exc:
            with state_lock:
                state["error_msg"] = str(exc)
                state["last_status"] = "error"
        
        time.sleep(CHECK_INTERVAL)

@app.route("/")
def index(): return render_template("index.html", interval=CHECK_INTERVAL)

@app.route("/api/status")
def api_status():
    with state_lock: return jsonify(dict(state))

if __name__ == "__main__":
    # Проверка наличия браузера перед запуском
    try:
        log.info("Проверка наличия браузера Playwright...")
        # Пытаемся запустить установку. Если он есть — команда пройдет мгновенно.
        subprocess.run(["playwright", "install", "chromium"], check=True)
        log.info("✅ Браузер готов к работе")
    except Exception as e:
        log.warning(f"⚠️ Не удалось запустить установку через subprocess: {e}")
        # Запасной вариант установки
        os.system("playwright install chromium")

    # Запускаем фоновый поток мониторинга
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    log.info("🚀 Flask-сервер стартует на порту %s", os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
