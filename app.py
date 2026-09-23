from flask import Flask
import threading
import time
import os
import re
import traceback
from datetime import datetime, timedelta, timezone
import vk_api
import requests

app = Flask(__name__)

# --- НАСТРОЙКИ ---
VK_TOKEN = os.environ.get("VK_TOKEN", "")
MY_USER_ID = int(os.environ.get("MY_USER_ID", "0"))
STOCK_API_KEY = os.environ.get("STOCK_API_KEY", "")
STOCK_URL = "https://raw.githubusercontent.com/iamishan877-max/Blox-Fruits-Stock/main/data/stock.json"
CHECK_INTERVAL = 60

MSK = timezone(timedelta(hours=3))

vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()


def log(msg):
    ts = datetime.now(MSK).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def send_vk_message(user_id, text):
    try:
        vk.messages.send(user_id=user_id, message=text, random_id=0)
        log(f"[VK] Отправлено: {text[:50]}...")
        return True
    except Exception as e:
        log(f"[VK] Ошибка отправки: {e}")
        return False


def get_stock():
    try:
        headers = {"X-API-Key": STOCK_API_KEY}
        r = requests.get(STOCK_URL, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        if "data" in data:
            return data["data"]
        return data
    except Exception as e:
        log(f"[Stock] Ошибка загрузки: {e}")
        return None


def format_fruits(fruit_list):
    names = []
    if not fruit_list:
        return names
    for item in fruit_list:
        name = item.get("name", "").strip()
        if name:
            names.append(name)
    return names


def get_update_times(stock_type):
    """Все возможные времена обновления за одни сутки (только часы)."""
    if stock_type == "normal":
        return [3, 7, 11, 15, 19, 23]
    else:  # mirage
        return list(range(1, 24, 2))  # 1,3,5,...,23


def time_info(stock_type):
    """
    Возвращает строку вида:
    🕐 Сток 03:00 → 07:00 МСК
    """
    try:
        now = datetime.now(MSK)
        hours = get_update_times(stock_type)
        current_hour = now.hour

        # Ищем ближайший прошедший час из списка (или предыдущий день)
        past = [h for h in hours if h <= current_hour]
        if past:
            start_hour = max(past)
            # Конец — следующий час из списка
            future = [h for h in hours if h > start_hour]
            if future:
                end_hour = min(future)
            else:
                end_hour = min(hours)  # переход через полночь
        else:
            # Сейчас раньше самого первого обновления дня — сток идёт с вчера
            start_hour = max(hours)
            end_hour = min(hours)

        start_str = f"{start_hour:02d}:00"
        end_str = f"{end_hour:02d}:00"
        return f"\n\n🕐 Сток {start_str} → {end_str} МСК"
    except Exception as e:
        log(f"[Time] Ошибка: {e}")
        return ""


def get_bot_history(count=100):
    try:
        history = vk.messages.getHistory(user_id=MY_USER_ID, count=count)
        return [m for m in history["items"] if m.get("from_id", 0) < 0]
    except Exception as e:
        log(f"[VK] Ошибка истории: {e}")
        return []


def parse_message_fruits(text):
    fruits = set()
    if not text:
        return fruits
    for line in text.splitlines():
        m = re.match(r"^\d+\.\s*(.+)$", line.strip())
        if m:
            fruits.add(m.group(1).strip())
    return fruits


def cleanup_duplicates():
    try:
        messages = get_bot_history(100)
        seen = {}
        to_delete = []
        for msg in messages:
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            if text in seen:
                to_delete.append(msg["id"])
            else:
                seen[text] = msg["id"]

        if to_delete:
            try:
                for i in range(0, len(to_delete), 100):
                    chunk = to_delete[i:i+100]
                    vk.messages.delete(
                        message_ids=",".join(str(x) for x in chunk),
                        delete_for_all=1
                    )
                log(f"[VK] Удалено дубликатов: {len(to_delete)}")
            except Exception as e:
                log(f"[VK] Ошибка удаления дубликатов: {e}")

        last_normal_text = None
        last_mirage_text = None
        for msg in messages:
            text = msg.get("text") or ""
            if text.startswith("🍎 ОБЫЧНЫЙ СТОК") and last_normal_text is None:
                last_normal_text = text
            elif text.startswith("✨ МИРАЖНЫЙ СТОК") and last_mirage_text is None:
                last_mirage_text = text
            if last_normal_text and last_mirage_text:
                break

        return last_normal_text, last_mirage_text
    except Exception as e:
        log(f"[Cleanup] Ошибка: {e}")
        return None, None


def process_iteration(last_normal_set, last_mirage_set):
    data = get_stock()
    if not data:
        return last_normal_set, last_mirage_set

    normal = format_fruits(data.get("normal", []))
    mirage = format_fruits(data.get("mirage", []))
    normal_set = set(normal)
    mirage_set = set(mirage)

    # --- Normal ---
    if not last_normal_set:
        log(f"[Startup] Normal: {', '.join(normal)}")
        msg = "🍎 ОБЫЧНЫЙ СТОК\n" + "\n".join(f"{i}. {f}" for i, f in enumerate(normal, 1))
        msg += time_info("normal")
        send_vk_message(MY_USER_ID, msg)
        last_normal_set = normal_set
    elif normal_set != last_normal_set:
        log(f"[Stock] Normal обновился: {', '.join(normal)}")
        msg = "🍎 ОБЫЧНЫЙ СТОК\n" + "\n".join(f"{i}. {f}" for i, f in enumerate(normal, 1))
        msg += time_info("normal")
        send_vk_message(MY_USER_ID, msg)
        last_normal_set = normal_set

    # --- Mirage ---
    if not last_mirage_set:
        log(f"[Startup] Mirage: {', '.join(mirage)}")
        msg = "✨ МИРАЖНЫЙ СТОК\n" + "\n".join(f"{i}. {f}" for i, f in enumerate(mirage, 1))
        msg += time_info("mirage")
        send_vk_message(MY_USER_ID, msg)
        last_mirage_set = mirage_set
    elif mirage_set != last_mirage_set:
        log(f"[Stock] Mirage обновился: {', '.join(mirage)}")
        msg = "✨ МИРАЖНЫЙ СТОК\n" + "\n".join(f"{i}. {f}" for i, f in enumerate(mirage, 1))
        msg += time_info("mirage")
        send_vk_message(MY_USER_ID, msg)
        last_mirage_set = mirage_set

    return last_normal_set, last_mirage_set


def bot_loop():
    log("Бот запущен. Слежу за стоком...")

    last_normal_text, last_mirage_text = cleanup_duplicates()
    last_normal_set = parse_message_fruits(last_normal_text)
    last_mirage_set = parse_message_fruits(last_mirage_text)

    if last_normal_text:
        log("[Startup] Последний Normal найден в истории.")
    if last_mirage_text:
        log("[Startup] Последний Mirage найден в истории.")

    while True:
        try:
            last_normal_set, last_mirage_set = process_iteration(
                last_normal_set, last_mirage_set
            )
        except Exception as e:
            log(f"[Loop] Ошибка в итерации: {e}")
            log(traceback.format_exc())
        time.sleep(CHECK_INTERVAL)


def run_bot_forever():
    while True:
        try:
            bot_loop()
        except Exception as e:
            log(f"[Supervisor] bot_loop упал: {e}")
            log(traceback.format_exc())
            log("[Supervisor] Перезапуск через 5 секунд...")
            time.sleep(5)


@app.route('/')
def index():
    return "Stock bot is running."


if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot_forever, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=8080)
