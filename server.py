import base64
import json
import os
import socket
import sys
import threading
import tkinter as tk
import traceback

from config import (PORT, BUFFER_SIZE, ENCODING, COMMAND_LIST, COMMAND_SELECT, COMMAND_MODEL, COMMAND_PHOTO,
                    REPLY_OK, REPLY_ERROR, MESSAGE_END, MAX_COMMAND_SIZE, DISCOVERY_PORT)
from discovery import DiscoveryResponder
from model_view import ModelView, load_photo

# exe от PyInstaller распаковывает папку data во временную папку sys._MEIPASS
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
PHOTO_FIELDS = ("title", "author", "license", "license_url", "source")


class CommandError(Exception):
    pass


def load_catalog():
    with open(os.path.join(DATA_DIR, "models.json"), encoding="utf-8") as file:
        models = json.load(file)["models"]
    return {model["id"]: model for model in models}


class ServerApp:
    def __init__(self):
        self.server_socket = None
        self.client_sockets = set()
        self.clients_lock = threading.Lock()
        self.selection_lock = threading.Lock()
        self.selection_number = 0
        self.running = True
        self.discovery = DiscoveryResponder()

        try:
            self.catalog = load_catalog()
            catalog_error = None if self.catalog else "Каталог пуст"
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.catalog = {}
            catalog_error = f"Нет данных каталога ({error}). Запустите fetch_data.py"

        self.root = tk.Tk()
        self.root.title("Сервер (Ноутбук 1)")
        self.root.geometry("1100x660")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.status_label = tk.Label(self.root, text="Запуск сервера...", font=("Arial", 12))
        self.status_label.pack(pady=(10, 0))

        self.discovery_label = tk.Label(self.root, text="", font=("Arial", 9), fg="gray")
        self.discovery_label.pack()

        self.view = ModelView(self.root)
        self.view.pack(fill=tk.BOTH, expand=True, pady=10)
        self.view.show_message(catalog_error or "Ожидание выбора модели на клиенте...", error=bool(catalog_error))

    def start(self):
        try:
            self.discovery.start()
            discovery_text = f"Поиск: порт {DISCOVERY_PORT}, имя «{self.discovery.name}»"
        except OSError as error:
            discovery_text = f"Автопоиск недоступен: {error}"
        self.discovery_label.config(text=discovery_text)

        listen_thread = threading.Thread(target=self.listen_for_clients, daemon=True)
        listen_thread.start()
        self.root.mainloop()

    def listen_for_clients(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("0.0.0.0", PORT))
            self.server_socket.listen(5)
        except OSError as error:
            self.set_status(f"Ошибка запуска сервера: {error}")
            return

        self.set_status(f"Ожидание клиента... (порт {PORT})")
        while self.running:
            try:
                connection, address = self.server_socket.accept()
            except OSError:
                break
            with self.clients_lock:
                self.client_sockets.add(connection)
            threading.Thread(target=self.serve_client, args=(connection, address), daemon=True).start()

    def serve_client(self, connection, address):
        self.set_status(f"Клиент подключён: {address[0]} (всего: {len(self.client_sockets)})")
        self.receive_commands(connection, address)
        with self.clients_lock:
            self.client_sockets.discard(connection)
            count = len(self.client_sockets)
        self.close_socket(connection)
        if self.running:
            if count:
                self.set_status(f"Клиент {address[0]} отключился (осталось: {count})")
            else:
                self.set_status("Соединение потеряно. Ожидание клиента...")

    def receive_commands(self, connection, address):
        buffer = b""
        end_bytes = MESSAGE_END.encode(ENCODING)
        while self.running:
            try:
                data = connection.recv(BUFFER_SIZE)
            except OSError:
                return
            if not data:
                return

            buffer += data
            while end_bytes in buffer:
                message, buffer = buffer.split(end_bytes, 1)
                if len(message) > MAX_COMMAND_SIZE:
                    reply = f"{REPLY_ERROR} слишком длинная команда"
                else:
                    reply = self.handle_command(message.decode(ENCODING, errors="ignore").strip(), address)
                if not self.send_reply(connection, reply):
                    return
            if len(buffer) > MAX_COMMAND_SIZE:
                # строка без конца сообщения: это не наш клиент, соединение закрывается
                self.send_reply(connection, f"{REPLY_ERROR} слишком длинная команда")
                return

    def handle_command(self, command, address):
        name, _, argument = command.partition(" ")
        try:
            if name == COMMAND_LIST:
                return self.list_models()
            if name == COMMAND_SELECT:
                return self.select_model(argument, address)
            if name == COMMAND_MODEL:
                return self.describe_model(argument)
            if name == COMMAND_PHOTO:
                return self.send_photo(argument)
            raise CommandError("неизвестная команда")
        except CommandError as error:
            return f"{REPLY_ERROR} {error}"
        except Exception:
            traceback.print_exc()
            return f"{REPLY_ERROR} внутренняя ошибка сервера"

    def find_model(self, model_id):
        # модель ищется только среди известных id, строка клиента дальше не используется
        model = self.catalog.get(model_id.strip())
        if model is None:
            raise CommandError("неизвестная модель" if self.catalog else "на сервере нет данных каталога")
        return model

    def list_models(self):
        if not self.catalog:
            raise CommandError("на сервере нет данных каталога")
        models = [{"id": model["id"], "name": model["name"]} for model in self.catalog.values()]
        return f"{REPLY_OK} {json.dumps(models, ensure_ascii=False)}"

    def describe_model(self, model_id):
        model = self.find_model(model_id)
        photos = [{key: photo.get(key) for key in PHOTO_FIELDS} for photo in model.get("photos", [])]
        data = {"id": model["id"], "name": model["name"], "article": model.get("article"),
                "specs": model.get("specs", {}), "photos": photos}
        return f"{REPLY_OK} {json.dumps(data, ensure_ascii=False)}"

    def send_photo(self, argument):
        model_id, _, index_text = argument.strip().partition(" ")
        model = self.find_model(model_id)
        photos = model.get("photos", [])
        try:
            index = int(index_text)
        except ValueError:
            raise CommandError("неверный номер фото") from None
        if not 0 <= index < len(photos):
            raise CommandError("неверный номер фото")
        try:
            with open(self.photo_path(model, photos[index]), "rb") as file:
                data = file.read()
        except OSError:
            raise CommandError("файл фото не найден на сервере") from None
        return f"{REPLY_OK} {base64.b64encode(data).decode('ascii')}"

    def photo_path(self, model, photo):
        return os.path.join(DATA_DIR, "photos", model["id"], os.path.basename(photo["file"]))

    def select_model(self, model_id, address):
        model = self.find_model(model_id)
        with self.selection_lock:
            self.selection_number += 1
            number = self.selection_number
        self.run_in_ui(self.show_loading, number, model)
        self.set_status(f"Клиент {address[0]} выбрал: {model['name']}")
        threading.Thread(target=self.load_model_photos, args=(number, model), daemon=True).start()
        return REPLY_OK

    def load_model_photos(self, number, model):
        images = []
        for photo in model.get("photos", []):
            if number != self.selection_number:
                return  # пока грузили, кто-то из клиентов выбрал другую модель
            try:
                with open(self.photo_path(model, photo), "rb") as file:
                    images.append(load_photo(file.read()))
            except (OSError, ValueError):
                images.append(None)
        self.run_in_ui(self.show_model, number, model, images)

    def show_loading(self, number, model):
        if number == self.selection_number:
            self.view.show_message(f"Загрузка… ({model['name']})")

    def show_model(self, number, model, images):
        if number == self.selection_number:
            self.view.show_model(model, images)

    def send_reply(self, connection, reply):
        try:
            connection.sendall((reply + MESSAGE_END).encode(ENCODING))
            return True
        except OSError:
            return False

    def set_status(self, text):
        self.run_in_ui(self.status_label.config, {"text": text})

    def run_in_ui(self, function, *args):
        try:
            self.root.after(0, function, *args)
        except (RuntimeError, tk.TclError):
            pass

    def close_socket(self, sock):
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()

    def close(self):
        self.running = False
        self.discovery.stop()
        with self.clients_lock:
            client_sockets = list(self.client_sockets)
        for sock in client_sockets:
            self.close_socket(sock)
        if self.server_socket is not None:
            self.server_socket.close()
        self.root.destroy()


if __name__ == "__main__":
    ServerApp().start()
