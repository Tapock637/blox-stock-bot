from flask import Flask
import threading
import time
import os
import re
import vk_api
import requests

app = Flask(__name__)

# --- НАСТРОЙКИ ---
VK_TOKEN = os.environ.get("VK_TOKEN", "")
MY_USER_ID = int(os.environ.get("MY_USER_ID", "0"))
STOCK_URL = "https://raw.githubusercontent.com/iamishan877-max/Blox-Fruits-Stock/main/data/stock.json"
CHECK_INTERVAL = 60

vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()


def send_vk_message(user_id, text):
    try:
        vk.messages.send(user_id=user_id, message=text, random_id=0)
        print(f"[VK] Отправлено: {text[:60]}...")
    except Exception as e:
        print(f"[VK] Ошибка отправки: {e}")


def get_stock():
    try:
        r = requests.get(STOCK_URL, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[Stock] Ошибка загрузки: {e}")
        return None


def format_fruits(fruit_list):
    names = []
    for item in fruit_list:
        name = item.get("name", "").split("-")[0].strip()
        if name:
            names.append(name)
    return names


def get_bot_history(count=100):
    """Возвращает список последних сообщений от бота (от сообщества)."""
    try:
        history = vk.messages.getHistory(user_id=MY_USER_ID, count=count)
        # сообщения от сообщества имеют отрицательный from_id
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
    Возвращает последние тексты Normal и Mirage.
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
                # ничего в истории — просто запоминаем
                print(f"[Startup] Normal: {', '.join(normal)}")
                last_normal_set = normal_set
            elif normal_set != last_normal_set:
                print(f"[Stock] Normal обновился: {', '.join(normal)}")
                msg = "🍎 ОБЫЧНЫЙ СТОК\n" + "\n".join(
                    f"{i}. {f}" for i, f in enumerate(normal, 1)
                )
                send_vk_message(MY_USER_ID, msg)
                last_normal_set = normal_set

            # --- Mirage ---
            if not last_mirage_set:
                print(f"[Startup] Mirage: {', '.join(mirage)}")
                last_mirage_set = mirage_set
            elif mirage_set != last_mirage_set:
                print(f"[Stock] Mirage обновился: {', '.join(mirage)}")
                msg = "✨ МИРАЖНЫЙ СТОК\n" + "\n".join(
                    f"{i}. {f}" for i, f in enumerate(mirage, 1)
                )
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
