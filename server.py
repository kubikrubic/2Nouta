import socket
import threading
import tkinter as tk

from config import PORT, BUFFER_SIZE, ENCODING, COMMAND_START, COMMAND_STOP, MESSAGE_END


class ServerApp:
    def __init__(self):
        self.server_socket = None
        self.client_socket = None
        self.running = True

        self.root = tk.Tk()
        self.root.title("Сервер (Ноутбук 1)")
        self.root.geometry("360x330")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.status_label = tk.Label(self.root, text="Запуск сервера...", font=("Arial", 12))
        self.status_label.pack(pady=10)

        self.canvas = tk.Canvas(self.root, width=300, height=240, bg="white")
        self.canvas.pack(pady=10)
        self.show_text()

    def start(self):
        listen_thread = threading.Thread(target=self.listen_for_clients, daemon=True)
        listen_thread.start()
        self.root.mainloop()

    def listen_for_clients(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("0.0.0.0", PORT))
            self.server_socket.listen(1)
        except OSError as error:
            self.set_status(f"Ошибка запуска сервера: {error}")
            return

        waiting_text = f"Ожидание клиента... (порт {PORT})"
        while self.running:
            self.set_status(waiting_text)
            try:
                connection, address = self.server_socket.accept()
            except OSError:
                break

            self.client_socket = connection
            self.set_status(f"Клиент подключён: {address[0]}")
            self.receive_commands(connection)
            self.close_socket(connection)
            self.client_socket = None
            waiting_text = "Соединение потеряно. Ожидание клиента..."

    def receive_commands(self, connection):
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
                command = message.decode(ENCODING, errors="ignore").strip()
                self.handle_command(command)

    def handle_command(self, command):
        if command == COMMAND_START:
            self.run_in_ui(self.show_square)
        elif command == COMMAND_STOP:
            self.run_in_ui(self.show_text)
        else:
            return
        self.set_status(f"Получена команда: {command}")

    def show_square(self):
        self.canvas.delete("all")
        self.canvas.create_rectangle(90, 60, 210, 180, fill="royalblue", outline="navy", width=3)

    def show_text(self):
        self.canvas.delete("all")
        self.canvas.create_text(150, 120, text="Привет! Это текст.", font=("Arial", 18))

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
        self.close_socket(self.client_socket)
        if self.server_socket is not None:
            self.server_socket.close()
        self.root.destroy()


if __name__ == "__main__":
    ServerApp().start()
