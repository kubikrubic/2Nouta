import base64
import ipaddress
import json
import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import ttk

from config import (PORT, BUFFER_SIZE, ENCODING, COMMAND_LIST, COMMAND_SELECT, COMMAND_MODEL, COMMAND_PHOTO,
                    REPLY_OK, REPLY_ERROR, MESSAGE_END, MAX_MESSAGE_SIZE, REPLY_TIMEOUT, SAVED_IP_TIMEOUT)
from discovery import probe, scan, get_local_ip, get_network, load_last_ip, save_last_ip
from model_view import ModelView, load_photo


class ServerError(Exception):
    pass


def describe_error(error):
    if isinstance(error, ServerError):
        return f"Сервер ответил ошибкой: {error}"
    if isinstance(error, OSError):
        return f"Нет связи с сервером: {error}"
    return "Сервер прислал некорректный ответ"


class ClientApp:
    def __init__(self, server_ip=None):
        self.server_ip = server_ip
        self.server_name = None
        self.client_socket = None
        self.replies = None
        self.request_lock = threading.Lock()
        self.models = []
        self.selected_id = None
        self.request_number = 0
        self.running = True

        self.root = tk.Tk()
        self.root.title("Клиент (Ноутбук 2)")
        self.root.geometry("1100x740")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.status_label = tk.Label(self.root, text="", font=("Arial", 12), wraplength=1000)
        self.status_label.pack(pady=(10, 5))

        catalog_frame = tk.Frame(self.root)
        catalog_frame.pack(pady=5)
        tk.Label(catalog_frame, text="Модель Lada:", font=("Arial", 12)).pack(side=tk.LEFT)
        self.model_box = ttk.Combobox(catalog_frame, state=tk.DISABLED, width=28, font=("Arial", 12))
        self.model_box.pack(side=tk.LEFT, padx=5)
        self.model_box.bind("<<ComboboxSelected>>", lambda event: self.on_model_selected())

        connection_frame = tk.Frame(self.root)
        connection_frame.pack(pady=5)
        tk.Label(connection_frame, text="IP сервера:").pack(side=tk.LEFT)
        self.ip_entry = tk.Entry(connection_frame, width=16)
        self.ip_entry.insert(0, server_ip or load_last_ip() or "")
        self.ip_entry.pack(side=tk.LEFT, padx=5)
        self.ip_entry.bind("<Return>", lambda event: self.on_manual_connect())
        self.manual_button = tk.Button(connection_frame, text="Подключиться", state=tk.DISABLED,
                                       command=self.on_manual_connect)
        self.manual_button.pack(side=tk.LEFT)

        self.search_button = tk.Button(connection_frame, text="Найти в сети", state=tk.DISABLED, command=self.discover)
        self.search_button.pack(side=tk.LEFT, padx=5)

        self.reconnect_button = tk.Button(connection_frame, text="Переподключиться", state=tk.DISABLED,
                                          command=self.connect)
        self.reconnect_button.pack(side=tk.LEFT)

        self.view = ModelView(self.root)
        self.view.pack(fill=tk.BOTH, expand=True, pady=5)
        self.view.show_message("Каталог появится после подключения к серверу")

    def start(self):
        if self.server_ip:
            self.connect()
        else:
            self.discover()
        self.root.mainloop()

    def set_busy(self, text):
        self.status_label.config(text=text, fg="black")
        self.model_box.config(state=tk.DISABLED)
        for button in (self.reconnect_button, self.manual_button, self.search_button):
            button.config(state=tk.DISABLED)

    def set_idle(self, text):
        self.status_label.config(text=text, fg="firebrick")
        self.model_box.config(state=tk.DISABLED)
        self.reconnect_button.config(state=tk.NORMAL if self.server_ip else tk.DISABLED)
        self.manual_button.config(state=tk.NORMAL)
        self.search_button.config(state=tk.NORMAL)

    def discover(self):
        self.set_busy("Поиск сервера...")
        discover_thread = threading.Thread(target=self.discover_server, daemon=True)
        discover_thread.start()

    def discover_server(self):
        saved_ip = load_last_ip()
        if saved_ip:
            self.run_in_ui(self.status_label.config, {"text": f"Проверка последнего адреса {saved_ip}..."})
            device = probe(saved_ip, SAVED_IP_TIMEOUT)
            if device:
                self.run_in_ui(self.on_server_found, device, 1)
                return

        local_ip = get_local_ip()
        if local_ip is None:
            hosts = ["127.0.0.1"]
            text = "Сеть не найдена, проверка этого компьютера..."
        else:
            network = get_network(local_ip)
            hosts = list(network.hosts())
            text = f"Поиск сервера в сети {network} ({len(hosts)} адресов)..."
        self.run_in_ui(self.status_label.config, {"text": text})

        devices = scan(hosts)
        if devices:
            self.run_in_ui(self.on_server_found, devices[0], len(devices))
        else:
            self.run_in_ui(self.on_server_not_found)

    def on_server_found(self, device, count):
        if not self.running:
            return
        if count > 1:
            print(f"Ответили {count} устройств, выбрано самое быстрое: {device.name} ({device.ip})")
        self.server_ip = device.ip
        self.server_name = device.name
        save_last_ip(device.ip)
        self.ip_entry.delete(0, tk.END)
        self.ip_entry.insert(0, device.ip)
        self.connect()

    def on_server_not_found(self):
        if not self.running:
            return
        self.set_idle("Сервер не найден в сети. Введите IP вручную или повторите поиск.")

    def on_manual_connect(self):
        if self.manual_button["state"] == tk.DISABLED:
            return
        ip = self.ip_entry.get().strip()
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            self.status_label.config(text=f"Неверный IP: «{ip}»", fg="firebrick")
            return
        self.server_ip = ip
        self.server_name = None
        self.connect()

    def connect(self):
        self.set_busy(f"Подключение к {self.server_ip}:{PORT}...")
        connect_thread = threading.Thread(target=self.connect_to_server, daemon=True)
        connect_thread.start()

    def connect_to_server(self):
        new_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        new_socket.settimeout(3)
        try:
            new_socket.connect((self.server_ip, PORT))
        except OSError:
            new_socket.close()
            self.run_in_ui(self.on_connection_lost, "Не удалось подключиться к серверу")
            return

        new_socket.settimeout(None)
        replies = queue.Queue()
        self.replies = replies
        self.client_socket = new_socket
        self.run_in_ui(self.on_connected)
        self.receive_replies(new_socket, replies)

    def receive_replies(self, connection, replies):
        # единственный поток, который читает сокет: ответы по очереди уходят в request()
        buffer = bytearray()
        end_bytes = MESSAGE_END.encode(ENCODING)
        while self.running:
            try:
                data = connection.recv(BUFFER_SIZE)
            except OSError:
                break
            if not data:
                break

            search_from = max(0, len(buffer) - len(end_bytes) + 1)
            buffer += data
            position = buffer.find(end_bytes, search_from)
            while position >= 0:
                replies.put(buffer[:position].decode(ENCODING, errors="ignore"))
                del buffer[:position + len(end_bytes)]
                position = buffer.find(end_bytes)
            if len(buffer) > MAX_MESSAGE_SIZE:
                break

        replies.put(None)
        if self.client_socket is connection:
            self.client_socket = None
            connection.close()
            self.run_in_ui(self.on_connection_lost, "Соединение с сервером потеряно")

    def request(self, command):
        """Отправляет команду и ждёт ответ. Вызывается только из фоновых потоков."""
        with self.request_lock:
            connection, replies = self.client_socket, self.replies
            if connection is None:
                raise ConnectionError("нет подключения")
            connection.sendall((command + MESSAGE_END).encode(ENCODING))
            try:
                reply = replies.get(timeout=REPLY_TIMEOUT)
            except queue.Empty:
                # поздний ответ перепутал бы очередь, поэтому соединение разрывается
                self.disconnect()
                self.run_in_ui(self.on_connection_lost, "Сервер не отвечает")
                raise ConnectionError("сервер не отвечает") from None
        if reply is None:
            raise ConnectionError("соединение потеряно")
        status, _, payload = reply.partition(" ")
        if status == REPLY_ERROR:
            raise ServerError(payload or "без описания")
        if status != REPLY_OK:
            raise ValueError("неизвестный ответ сервера")
        return payload

    def on_connected(self):
        save_last_ip(self.server_ip)
        name = f"{self.server_name} " if self.server_name else ""
        self.status_label.config(text=f"Подключено к {name}{self.server_ip}:{PORT}. Загрузка каталога...", fg="black")
        threading.Thread(target=self.fetch_catalog, daemon=True).start()

    def fetch_catalog(self):
        try:
            models = [{"id": str(model["id"]), "name": str(model["name"])}
                      for model in json.loads(self.request(COMMAND_LIST))]
        except (OSError, ServerError, ValueError, KeyError, TypeError) as error:
            self.run_in_ui(self.on_catalog_failed, describe_error(error))
            return
        self.run_in_ui(self.on_catalog_loaded, models)

    def on_catalog_loaded(self, models):
        if not self.running or self.client_socket is None:
            return
        self.models = models
        self.model_box.config(values=[model["name"] for model in models], state="readonly")
        ids = [model["id"] for model in models]
        if self.selected_id in ids:
            # после переподключения сервер снова показывает выбранную модель
            self.model_box.current(ids.index(self.selected_id))
            self.select_model(models[ids.index(self.selected_id)])
        else:
            self.view.show_message("Выберите модель в списке")
        self.status_label.config(text=f"Подключено к {self.server_ip}:{PORT}. Моделей в каталоге: {len(models)}")

    def on_catalog_failed(self, text):
        if not self.running:
            return
        self.status_label.config(text=text, fg="firebrick")
        self.view.show_message(text, error=True)

    def on_model_selected(self):
        index = self.model_box.current()
        if 0 <= index < len(self.models):
            self.select_model(self.models[index])

    def select_model(self, model):
        self.selected_id = model["id"]
        self.request_number += 1
        number = self.request_number
        self.view.show_message(f"Загрузка… ({model['name']})")
        threading.Thread(target=self.fetch_model, args=(number, model), daemon=True).start()

    def fetch_model(self, number, model):
        # номер запроса сверяется перед каждым шагом: если уже выбрана другая модель, этот поток просто выходит
        model_id = model["id"]
        try:
            self.request(f"{COMMAND_SELECT} {model_id}")
            if number != self.request_number:
                return
            data = json.loads(self.request(f"{COMMAND_MODEL} {model_id}"))
            photos = data.get("photos") or []
            images = []
            for index in range(len(photos)):
                if number != self.request_number:
                    return
                self.run_in_ui(self.on_model_progress, number, model, index + 1, len(photos))
                try:
                    reply = self.request(f"{COMMAND_PHOTO} {model_id} {index}")
                except ServerError:
                    images.append(None)
                    continue
                try:
                    images.append(load_photo(base64.b64decode(reply, validate=True)))
                except (ValueError, OSError):
                    images.append(None)
        except (OSError, ServerError, ValueError, KeyError, TypeError, AttributeError) as error:
            self.run_in_ui(self.on_model_failed, number, describe_error(error))
            return
        self.run_in_ui(self.on_model_loaded, number, data, images)

    def on_model_progress(self, number, model, current, total):
        if number == self.request_number:
            self.view.show_message(f"Загрузка… ({model['name']}, фото {current} из {total})")

    def on_model_loaded(self, number, data, images):
        if number != self.request_number:
            return  # запоздавший ответ по старому выбору
        self.view.show_model(data, images)

    def on_model_failed(self, number, text):
        if number != self.request_number:
            return
        self.view.show_message(text, error=True)

    def on_connection_lost(self, text):
        if not self.running:
            return
        self.set_idle(text)

    def disconnect(self):
        old_socket = self.client_socket
        self.client_socket = None
        if old_socket is None:
            return
        try:
            old_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        old_socket.close()

    def run_in_ui(self, function, *args):
        try:
            self.root.after(0, function, *args)
        except (RuntimeError, tk.TclError):
            pass

    def close(self):
        self.running = False
        self.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    server_ip = sys.argv[1] if len(sys.argv) > 1 else None
    ClientApp(server_ip).start()
