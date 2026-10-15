import ipaddress
import socket
import sys
import threading
import tkinter as tk

from config import PORT, BUFFER_SIZE, ENCODING, COMMAND_START, COMMAND_STOP, MESSAGE_END, SAVED_IP_TIMEOUT
from discovery import probe, scan, get_local_ip, get_network, load_last_ip, save_last_ip


class ClientApp:
    def __init__(self, server_ip=None):
        self.server_ip = server_ip
        self.server_name = None
        self.client_socket = None
        self.is_started = False
        self.running = True

        self.root = tk.Tk()
        self.root.title("Клиент (Ноутбук 2)")
        self.root.geometry("380x300")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.status_label = tk.Label(self.root, text="", font=("Arial", 12), wraplength=360)
        self.status_label.pack(pady=10)

        self.toggle_button = tk.Button(self.root, text="Start", font=("Arial", 16), padx=20, pady=10,
                                       state=tk.DISABLED, command=self.on_toggle_click)
        self.toggle_button.pack(pady=10)

        self.reconnect_button = tk.Button(self.root, text="Переподключиться", state=tk.DISABLED,
                                          command=self.connect)
        self.reconnect_button.pack(pady=5)

        manual_frame = tk.Frame(self.root)
        manual_frame.pack(pady=5)
        tk.Label(manual_frame, text="IP сервера:").pack(side=tk.LEFT)
        self.ip_entry = tk.Entry(manual_frame, width=16)
        self.ip_entry.insert(0, server_ip or load_last_ip() or "")
        self.ip_entry.pack(side=tk.LEFT, padx=5)
        self.ip_entry.bind("<Return>", lambda event: self.on_manual_connect())
        self.manual_button = tk.Button(manual_frame, text="Подключиться", state=tk.DISABLED,
                                       command=self.on_manual_connect)
        self.manual_button.pack(side=tk.LEFT)

        self.search_button = tk.Button(self.root, text="Найти в сети", state=tk.DISABLED, command=self.discover)
        self.search_button.pack(pady=5)

    def start(self):
        if self.server_ip:
            self.connect()
        else:
            self.discover()
        self.root.mainloop()

    def set_busy(self, text):
        self.status_label.config(text=text)
        for button in (self.toggle_button, self.reconnect_button, self.manual_button, self.search_button):
            button.config(state=tk.DISABLED)

    def set_idle(self, text):
        self.status_label.config(text=text)
        self.toggle_button.config(state=tk.DISABLED)
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
            # Сети нет — проверяем этот же компьютер
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
            self.status_label.config(text=f"Неверный IP: «{ip}»")
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
        self.client_socket = new_socket
        self.run_in_ui(self.on_connected)
        self.wait_for_disconnect(new_socket)

    def wait_for_disconnect(self, connection):
        while self.running:
            try:
                data = connection.recv(BUFFER_SIZE)
            except OSError:
                break
            if not data:
                break

        if self.client_socket is connection:
            self.client_socket = None
            connection.close()
            self.run_in_ui(self.on_connection_lost, "Соединение потеряно")

    def on_connected(self):
        save_last_ip(self.server_ip)
        name = f"{self.server_name} " if self.server_name else ""
        self.status_label.config(text=f"Подключено к {name}{self.server_ip}:{PORT}")
        self.toggle_button.config(state=tk.NORMAL)
        current_command = COMMAND_START if self.is_started else COMMAND_STOP
        self.send_command(current_command)

    def on_connection_lost(self, text):
        if not self.running:
            return
        self.set_idle(text)

    def on_toggle_click(self):
        command = COMMAND_STOP if self.is_started else COMMAND_START
        if self.send_command(command):
            self.is_started = not self.is_started
            self.toggle_button.config(text="Stop" if self.is_started else "Start")

    def send_command(self, command):
        if self.client_socket is None:
            return False
        try:
            self.client_socket.sendall((command + MESSAGE_END).encode(ENCODING))
            return True
        except OSError:
            self.disconnect()
            self.on_connection_lost("Соединение потеряно")
            return False

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
