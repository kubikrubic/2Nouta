import sys
import tkinter as tk

from client import ClientApp
from server import ServerApp


class RoleChooser:
    def __init__(self):
        self.role = None

        self.root = tk.Tk()
        self.root.title("2Nouta")
        self.root.geometry("320x230")
        self.root.resizable(False, False)

        tk.Label(self.root, text="Кем запустить этот ноутбук?", font=("Arial", 13)).pack(pady=15)

        tk.Button(self.root, text="Сервер\n(показывает квадрат / текст)", font=("Arial", 11), width=26,
                  command=lambda: self.choose("server")).pack(pady=5)
        tk.Button(self.root, text="Клиент\n(кнопка Start / Stop)", font=("Arial", 11), width=26,
                  command=lambda: self.choose("client")).pack(pady=5)

    def choose(self, role):
        self.role = role
        self.root.destroy()

    def ask(self):
        self.root.mainloop()
        return self.role


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else RoleChooser().ask()
    if role == "server":
        ServerApp().start()
    elif role == "client":
        ClientApp(sys.argv[2] if len(sys.argv) > 2 else None).start()
