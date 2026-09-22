from flask import Flask
import threading
import time
import os
import re
from datetime import datetime, timedelta, timezone
import vk_api
import requests

app = Flask(__name__)

# --- НАСТРОЙКИ ---
VK_TOKEN = os.environ.get("VK_TOKEN", "")
MY_USER_ID = int(os.environ.get("MY_USER_ID", "0"))

# Ключ API для стока (берётся из переменных окружения Render)
STOCK_API_KEY = os.environ.get("STOCK_API_KEY", "")
STOCK_URL = "https://api.parse.bot/scraper/e534d388-6640-4c19-b9b6-b2ba12930793/get_stock"

CHECK_INTERVAL = 60  # Проверка каждые 60 секунд

# Московское время (UTC+3)
MSK = timezone(timedelta(hours=3))

vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()


def send_vk_message(user_id, text):
    """Отправляет сообщение пользователю ВК."""
    try:
        vk.messages.send(user_id=user_id, message=text, random_id=0)
        print(f"[VK] Отправлено: {text[:60]}...")
    except Exception as e:
        print(f"[VK] Ошибка отправки: {e}")


def get_stock():
    """Загружает JSON с данными стока через Parse API."""
    try:
        headers = {"X-API-Key": STOCK_API_KEY}
        r = requests.get(STOCK_URL, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        # API возвращает объект с полем "data", внутри которого normal и mirage
        if "data" in data:
            return data["data"]
        return data
    except Exception as e:
        print(f"[Stock] Ошибка загрузки: {e}")
        return None


def format_fruits(fruit_list):
    """Превращает список словарей в список названий."""
    names = []
    for item in fruit_list:
        name = item.get("name", "").strip()
        if name:
            names.append(name)
    return names


# --- РАСЧЁТ ВРЕМЕНИ СТОКА (МСК) ---
def get_update_times(stock_type, now_msk):
    """Все времена обновления за вчера/сегодня/завтра (МСК)."""
    base = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
    times = []
    if stock_type == "normal":
        hours = [3, 7, 11, 15, 19, 23]
    else:  # mirage
        hours = list(range(1, 24, 2))  # 1,3,5,...,23
    for day_offset in (-1, 0, 1):
        day = base + timedelta(days=day_offset)
        for h in hours:
            times.append(day.replace(hour=h))
    return times


def format_delta(delta):
    """Форматирует timedelta в 'Xч Yмин' или 'Yмин'."""
    total_min = int(delta.total_seconds() // 60)
    hours = total_min // 60
    minutes = total_min % 60
    if hours > 0:
        return f"{hours}ч {minutes}мин"
    return f"{minutes}мин"


def time_info(stock_type):
    """Строка с временем текущего стока и таймером до следующего."""
    now = datetime.now(MSK)
    times = get_update_times(stock_type, now)
    last = max(t for t in times if t <= now)
    nxt = min(t for t in times if t > now)
    last_str = last.strftime("%H:%M")
    next_str = nxt.strftime("%H:%M")
    until = format_delta(nxt - now)
    return f"\n\n🕐 Сток от {last_str} МСК\n⏳ До обновления: {until} (в {next_str})"


# --- РАБОТА С ИСТОРИЕЙ ВК (УДАЛЕНИЕ ДУБЛИКАТОВ) ---
def get_bot_history(count=100):
    """Возвращает список последних сообщений от бота (от сообщества)."""
    try:
        history = vk.messages.getHistory(user_id=MY_USER_ID, count=count)
        return [m for m in history["items"] if m.get("from_id", 0) < 0]
    except Exception as e:
        print(f"[VK] Ошибка истории: {e}")
        return []


def parse_message_fruits(text):
    """Вытаскивает названия фруктов из текста сообщения."""
    fruits = set()
    if not text:
        return fruits
    for line in text.splitlines():
        m = re.match(r"^\d+\.\s*(.+)$", line.strip())
        if m:
            fruits.add(m.group(1).strip())
    return fruits


def cleanup_duplicates():
    """
    Удаляет дубликаты сообщений бота (одинаковый текст).
    Оставляет самое новое, старые — удаляет.
    """
    messages = get_bot_history(100)
    seen = {}
    to_delete = []
    for msg in messages:  # от новых к старым
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
            print(f"[VK] Удалено дубликатов: {len(to_delete)}")
        except Exception as e:
            print(f"[VK] Ошибка удаления дубликатов: {e}")

    # Ищем последний Normal и последний Mirage
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


def bot_loop():
    """Основной цикл бота."""
    print("Бот запущен в облаке. Слежу за стоком...")

    # При старте чистим дубликаты и запоминаем последние тексты
    last_normal_text, last_mirage_text = cleanup_duplicates()
    last_normal_set = parse_message_fruits(last_normal_text)
    last_mirage_set = parse_message_fruits(last_mirage_text)

    if last_normal_text:
        print("[Startup] Последний Normal уже в истории.")
    if last_mirage_text:
        print("[Startup] Последний Mirage уже в истории.")

    while True:
        data = get_stock()
        if data:
            normal = format_fruits(data.get("normal", []))
            mirage = format_fruits(data.get("mirage", []))
            normal_set = set(normal)
            mirage_set = set(mirage)

            # --- Normal ---
            if not last_normal_set:
                print(f"[Startup] Normal: {', '.join(normal)} — отправляю как первое")
                msg = "🍎 ОБЫЧНЫЙ СТОК\n" + "\n".join(
                    f"{i}. {f}" for i, f in enumerate(normal, 1)
                )
                msg += time_info("normal")
                send_vk_message(MY_USER_ID, msg)
                last_normal_set = normal_set
            elif normal_set != last_normal_set:
                print(f"[Stock] Normal обновился: {', '.join(normal)}")
                msg = "🍎 ОБЫЧНЫЙ СТОК\n" + "\n".join(
                    f"{i}. {f}" for i, f in enumerate(normal, 1)
                )
                msg += time_info("normal")
                send_vk_message(MY_USER_ID, msg)
                last_normal_set = normal_set

            # --- Mirage ---
            if not last_mirage_set:
                print(f"[Startup] Mirage: {', '.join(mirage)} — отправляю как первое")
                msg = "✨ МИРАЖНЫЙ СТОК\n" + "\n".join(
                    f"{i}. {f}" for i, f in enumerate(mirage, 1)
                )
                msg += time_info("mirage")
                send_vk_message(MY_USER_ID, msg)
                last_mirage_set = mirage_set
            elif mirage_set != last_mirage_set:
                print(f"[Stock] Mirage обновился: {', '.join(mirage)}")
                msg = "✨ МИРАЖНЫЙ СТОК\n" + "\n".join(
                    f"{i}. {f}" for i, f in enumerate(mirage, 1)
                )
                msg += time_info("mirage")
                send_vk_message(MY_USER_ID, msg)
                last_mirage_set = mirage_set

        time.sleep(CHECK_INTERVAL)


@app.route('/')
def index():
    return "Stock bot is running."


if __name__ == '__main__':
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=8080)
