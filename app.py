from flask import Flask
import threading
import time
import os
import vk_api
import requests

app = Flask(__name__)

# --- НАСТРОЙКИ (токен берётся из переменных окружения) ---
VK_TOKEN = os.environ.get("VK_TOKEN", "")
MY_USER_ID = int(os.environ.get("MY_USER_ID", "0"))

STOCK_URL = "https://raw.githubusercontent.com/iamishan877-max/Blox-Fruits-Stock/main/data/stock.json"
CHECK_INTERVAL = 60

vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()

def send_vk_message(user_id, text):
    try:
        vk.messages.send(user_id=user_id, message=text, random_id=0)
        print(f"[VK] Отправлено:\n{text}\n")
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

def bot_loop():
    last_normal = set()
    last_mirage = set()
    print("Бот запущен в облаке. Слежу за стоком...")
    while True:
        data = get_stock()
        if data:
            normal = format_fruits(data.get("normal", []))
            mirage = format_fruits(data.get("mirage", []))
            normal_set = set(normal)
            mirage_set = set(mirage)

            if normal_set != last_normal:
                print(f"[Stock] Normal обновился: {', '.join(normal)}")
                msg = "🍎 ОБЫЧНЫЙ СТОК\n" + "\n".join(f"{i}. {f}" for i, f in enumerate(normal, 1))
                send_vk_message(MY_USER_ID, msg)
                last_normal = normal_set

            if mirage_set != last_mirage:
                print(f"[Stock] Mirage обновился: {', '.join(mirage)}")
                msg = "✨ МИРАЖНЫЙ СТОК\n" + "\n".join(f"{i}. {f}" for i, f in enumerate(mirage, 1))
                send_vk_message(MY_USER_ID, msg)
                last_mirage = mirage_set
        time.sleep(CHECK_INTERVAL)

@app.route('/')
def index():
    return "Stock bot is running."

if __name__ == '__main__':
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()
    # Запускаем веб-сервер для Render
    app.run(host='0.0.0.0', port=8080)
