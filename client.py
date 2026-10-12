import socket
import sys
import threading
import tkinter as tk

from config import SERVER_IP, PORT, BUFFER_SIZE, ENCODING, COMMAND_START, COMMAND_STOP, MESSAGE_END


class ClientApp:
    def __init__(self, server_ip):
        self.server_ip = server_ip
        self.client_socket = None
        self.is_started = False
        self.running = True

        self.root = tk.Tk()
        self.root.title("Клиент (Ноутбук 2)")
        self.root.geometry("360x220")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.status_label = tk.Label(self.root, text="", font=("Arial", 12))
        self.status_label.pack(pady=10)

        self.toggle_button = tk.Button(self.root, text="Start", font=("Arial", 16), padx=20, pady=10,
                                       state=tk.DISABLED, command=self.on_toggle_click)
        self.toggle_button.pack(pady=10)

        self.reconnect_button = tk.Button(self.root, text="Переподключиться", state=tk.DISABLED,
                                          command=self.connect)
        self.reconnect_button.pack(pady=5)

    def start(self):
        self.connect()
        self.root.mainloop()

    def connect(self):
        self.toggle_button.config(state=tk.DISABLED)
        self.reconnect_button.config(state=tk.DISABLED)
        self.status_label.config(text=f"Подключение к {self.server_ip}:{PORT}...")
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
        self.status_label.config(text=f"Подключено к {self.server_ip}:{PORT}")
        self.toggle_button.config(state=tk.NORMAL)
        current_command = COMMAND_START if self.is_started else COMMAND_STOP
        self.send_command(current_command)

    def on_connection_lost(self, text):
        if not self.running:
            return
        self.status_label.config(text=text)
        self.toggle_button.config(state=tk.DISABLED)
        self.reconnect_button.config(state=tk.NORMAL)

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
    server_ip = sys.argv[1] if len(sys.argv) > 1 else SERVER_IP
    ClientApp(server_ip).start()
