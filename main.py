import sys
import traceback

ROLES = {"1": "server", "2": "client"}


def ask_role():
    while True:
        print()
        print("1 - Сервер")
        print("2 - Клиент")
        choice = input("Выберите режим: ").strip()
        if choice in ROLES:
            return ROLES[choice]
        print("Неверный выбор, введите 1 или 2.")


def run(role, server_ip=None):
    # импорт здесь, чтобы ошибка загрузки Tkinter попала в обработчик ниже и окно не закрылось
    if role == "server":
        from server import ServerApp
        print("Запуск сервера. Закройте окно сервера, чтобы выйти.")
        ServerApp().start()
    else:
        from client import ClientApp
        print("Запуск клиента. Закройте окно клиента, чтобы выйти.")
        ClientApp(server_ip).start()


def wait_for_key():
    print()
    print("Нажмите любую клавишу, чтобы закрыть окно...")
    try:
        import msvcrt
        msvcrt.getch()
    except ImportError:
        input()


def main():
    role = sys.argv[1] if len(sys.argv) > 1 else None
    if role not in (None, *ROLES.values()):
        print(f"Неизвестная роль «{role}». Допустимо: server, client [IP]")
        role = None
    if role is None:
        role = ask_role()
    run(role, sys.argv[2] if role == "client" and len(sys.argv) > 2 else None)


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
        print("Программа завершена.")
    except (KeyboardInterrupt, EOFError):
        print()
        print("Программа прервана.")
    except Exception:
        exit_code = 1
        print()
        print("Ошибка, программа остановлена:")
        traceback.print_exc()
    try:
        wait_for_key()
    except (KeyboardInterrupt, EOFError):
        pass
    sys.exit(exit_code)
