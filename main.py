import socket
import threading
import tkinter as tk
from tkinter import messagebox

# ========== НАСТРОЙКИ ==========
SERVER_IP = '10.23.250.18'  # <--- ЗАМЕНИ НА IP СЕРВЕРА (Ноутбук 1)
PORT = 55555
BUFFER_SIZE = 1024

# ========== ПЕРЕМЕННЫЕ СОСТОЯНИЯ ==========
# Этот флаг определяет, какая кнопка показывается на сервере
current_state = "Start"

# ========== ФУНКЦИИ ДЛЯ СЕРВЕРА (НОУТБУК 1) ==========
def start_server():
    """Запускает сервер, который ждет подключения клиента."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('0.0.0.0', PORT))  # Слушаем все доступные интерфейсы
    server_socket.listen(1)
    print(f"Сервер запущен. Ждем подключения на порту {PORT}...")

    # В цикле принимаем подключения (для лабы хватит одного)
    conn, addr = server_socket.accept()
    print(f"Подключился клиент: {addr}")
    
    # Запускаем поток для приема сообщений от клиента (если нужно)
    # В нашем простом случае мы только отправляем, поэтому поток не обязателен, 
    # но для надежности можно оставить.
    
    # Возвращаем сокет, чтобы использовать его в кнопке
    return conn

def on_button_click(conn):
    """Обработчик нажатия кнопки на сервере."""
    global current_state
    
    # Меняем состояние
    if current_state == "Start":
        current_state = "Stop"
        message = "CHANGE_TO_SQUARE"  # Команда для клиента: показать квадрат
    else:
        current_state = "Start"
        message = "CHANGE_TO_TEXT"    # Команда для клиента: показать текст

    # Отправляем команду клиенту
    try:
        conn.sendall(message.encode('utf-8'))
        print(f"Отправлено: {message}")
    except Exception as e:
        print(f"Ошибка отправки: {e}")
    
    # Меняем текст на кнопке сервера, чтобы было видно состояние
    btn_server.config(text=f"Кнопка: {current_state}")

# ========== ФУНКЦИИ ДЛЯ КЛИЕНТА (НОУТБУК 2) ==========
def start_client():
    """Подключается к серверу."""
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client_socket.connect((SERVER_IP, PORT))
        print(f"Подключено к серверу {SERVER_IP}:{PORT}")
        return client_socket
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось подключиться к серверу.\nПроверь IP и запущен ли сервер.\n{e}")
        return None

def receive_messages(client_socket, ui_elements):
    """Поток, который слушает сервер и обновляет UI."""
    while True:
        try:
            data = client_socket.recv(BUFFER_SIZE).decode('utf-8')
            if not data:
                break
            
            print(f"Получено: {data}")
            
            # Обновляем UI в главном потоке (tkinter не любит обновления из других потоков)
            # Для простоты используем метод after
            if data == "CHANGE_TO_SQUARE":
                # Показать квадратик
                ui_elements['root'].after(0, lambda: show_square(ui_elements))
            elif data == "CHANGE_TO_TEXT":
                # Показать текст
                ui_elements['root'].after(0, lambda: show_text(ui_elements))
                
        except Exception as e:
            print(f"Ошибка при получении: {e}")
            break

def show_square(ui):
    """Меняет интерфейс клиента: показывает квадрат."""
    ui['label'].config(text="Квадратик! 🔲", font=("Arial", 40))
    # Можно добавить Canvas и рисовать квадрат, но для лабы хватит смены текста

def show_text(ui):
    """Меняет интерфейс клиента: показывает текст."""
    ui['label'].config(text="Привет! Это текст.", font=("Arial", 20))

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    # Спросим у пользователя, кем он хочет быть
    role = input("Кто ты? (server/client): ").strip().lower()

    if role == 'server':
        # --- ЛОГИКА СЕРВЕРА ---
        conn = start_server()  # Блокируется, пока не подключится клиент
        
        root = tk.Tk()
        root.title("Сервер (Ноутбук 1)")
        root.geometry("300x200")
        
        btn_server = tk.Button(root, text="Кнопка: Start", 
                               command=lambda: on_button_click(conn),
                               font=("Arial", 14), padx=20, pady=10)
        btn_server.pack(expand=True)
        
        root.mainloop()

    elif role == 'client':
        # --- ЛОГИКА КЛИЕНТА ---
        root = tk.Tk()
        root.title("Клиент (Ноутбук 2)")
        root.geometry("300x200")
        
        label = tk.Label(root, text="Ожидание...", font=("Arial", 20))
        label.pack(expand=True)
        
        ui_elements = {'root': root, 'label': label}
        
        client_socket = start_client()
        if client_socket:
            # Запускаем поток для приема сообщений
            thread = threading.Thread(target=receive_messages, args=(client_socket, ui_elements), daemon=True)
            thread.start()
            
            root.mainloop()