import ipaddress
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

from config import (BUFFER_SIZE, ENCODING, MESSAGE_END, DISCOVERY_PORT, DISCOVER_REQUEST, DISCOVER_REPLY,
                    DISCOVERY_TIMEOUT, LAST_IP_FILE)

DEFAULT_PREFIX = 24   # если маску узнать не удалось
MIN_PREFIX = 22       # не сканируем больше 1022 адресов
MAX_WORKERS = 256
# В собранном exe __file__ указывает во временную папку, поэтому храним файл рядом с exe
APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
LAST_IP_PATH = os.path.join(APP_DIR, LAST_IP_FILE)
# Без этого флага в exe без консоли при вызове ipconfig мелькает чёрное окно
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

Device = namedtuple("Device", ["ip", "name", "response_time"])


def read_line(sock, limit=256):
    end_bytes = MESSAGE_END.encode(ENCODING)
    data = b""
    while end_bytes not in data and len(data) < limit:
        chunk = sock.recv(BUFFER_SIZE)
        if not chunk:
            break
        data += chunk
    return data.split(end_bytes, 1)[0].decode(ENCODING, errors="ignore").strip()


class DiscoveryResponder:
    """Отвечает на DISCOVER, чтобы клиент мог найти этот компьютер в сети."""

    def __init__(self, name=None):
        self.name = name or socket.gethostname()
        self.server_socket = None
        self.running = False

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("0.0.0.0", DISCOVERY_PORT))
        self.server_socket.listen(16)
        self.running = True
        threading.Thread(target=self.accept_requests, daemon=True).start()

    def accept_requests(self):
        while self.running:
            try:
                connection, _ = self.server_socket.accept()
            except OSError:
                break
            threading.Thread(target=self.answer, args=(connection,), daemon=True).start()

    def answer(self, connection):
        with connection:
            connection.settimeout(1)
            try:
                if read_line(connection) == DISCOVER_REQUEST:
                    reply = f"{DISCOVER_REPLY} {self.name}{MESSAGE_END}"
                    connection.sendall(reply.encode(ENCODING))
            except OSError:
                pass

    def stop(self):
        self.running = False
        if self.server_socket is None:
            return
        try:
            # shutdown будит поток в accept(); один close() на Linux этого не делает
            self.server_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.server_socket.close()


def probe(ip, timeout=DISCOVERY_TIMEOUT):
    """Отправляет DISCOVER на ip. Возвращает Device или None, если ответа HERE нет."""
    started = time.monotonic()
    try:
        with socket.create_connection((ip, DISCOVERY_PORT), timeout=timeout) as sock:
            sock.sendall((DISCOVER_REQUEST + MESSAGE_END).encode(ENCODING))
            reply = read_line(sock)
    except OSError:
        return None
    response_time = time.monotonic() - started

    command, _, name = reply.partition(" ")
    if command != DISCOVER_REPLY:
        return None
    return Device(ip, name.strip() or ip, response_time)


def scan(hosts, timeout=DISCOVERY_TIMEOUT):
    """Опрашивает адреса параллельно. Возвращает ответившие устройства, самое быстрое — первым."""
    hosts = [str(host) for host in hosts]
    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(hosts))) as pool:
        devices = [device for device in pool.map(lambda ip: probe(ip, timeout), hosts) if device]
    return sorted(devices, key=lambda device: device.response_time)


def get_local_ip():
    """IP интерфейса, через который идёт трафик в сеть (обычно Wi-Fi). None — если сети нет."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            # UDP connect ничего не отправляет, только выбирает интерфейс по таблице маршрутов
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
        except OSError:
            return None
    if ip.startswith("127.") or ip == "0.0.0.0":
        return None
    return ip


def find_prefix(ip):
    """Ищет длину маски подсети для ip в выводе системной команды. None — если не нашли."""
    commands = {"Windows": ["ipconfig"], "Darwin": ["ifconfig"]}
    command = commands.get(platform.system(), ["ip", "-o", "-4", "addr", "show"])
    try:
        output = subprocess.run(command, capture_output=True, timeout=3,
                                creationflags=NO_WINDOW).stdout.decode(errors="ignore")
    except (OSError, subprocess.SubprocessError):
        return None

    match = re.search(r"(?<![\d.])" + re.escape(ip) + r"(?![\d.])", output)
    if match is None:
        return None
    after_ip = output[match.end():match.end() + 300]

    # Linux: "192.168.0.5/24", macOS: "netmask 0xffffff00", Windows: строка "255.255.255.0" ниже
    patterns = [r"^/(\d{1,2})\b", r"netmask (0x[0-9a-fA-F]{8})", r"\b(255\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"]
    for pattern in patterns:
        found = re.search(pattern, after_ip)
        if found is None:
            continue
        mask = found.group(1)
        if mask.startswith("0x"):
            mask = str(ipaddress.IPv4Address(int(mask, 16)))
        try:
            return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
        except ValueError:
            return None
    return None


def get_network(ip):
    prefix = find_prefix(ip) or DEFAULT_PREFIX
    return ipaddress.IPv4Network(f"{ip}/{max(prefix, MIN_PREFIX)}", strict=False)


def load_last_ip():
    try:
        with open(LAST_IP_PATH, encoding="utf-8") as file:
            ip = file.read().strip()
        ipaddress.IPv4Address(ip)
        return ip
    except (OSError, ValueError):
        return None


def save_last_ip(ip):
    try:
        with open(LAST_IP_PATH, "w", encoding="utf-8") as file:
            file.write(ip)
    except OSError:
        pass
