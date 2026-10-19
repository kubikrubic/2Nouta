PORT = 55555
BUFFER_SIZE = 65536
ENCODING = "utf-8"

# Запрос клиента — одна строка, ответ сервера — одна строка "OK <данные>" или "ERROR <текст>".
# Фото идут по одному на ответ в base64, поэтому ответ может быть большим.
COMMAND_LIST = "LIST"        # LIST              -> OK [{"id", "name"}, ...]
COMMAND_SELECT = "SELECT"    # SELECT <id>       -> OK (сервер показывает модель у себя)
COMMAND_MODEL = "MODEL"      # MODEL <id>        -> OK {"id", "name", "specs", "photos"}
COMMAND_PHOTO = "PHOTO"      # PHOTO <id> <n>    -> OK <base64 файла фото>
REPLY_OK = "OK"
REPLY_ERROR = "ERROR"
MESSAGE_END = "\n"
MAX_COMMAND_SIZE = 256
MAX_MESSAGE_SIZE = 8 * 1024 * 1024
REPLY_TIMEOUT = 15

DISCOVERY_PORT = 55556
DISCOVER_REQUEST = "DISCOVER"
DISCOVER_REPLY = "HERE"
DISCOVERY_TIMEOUT = 0.3
SAVED_IP_TIMEOUT = 1.0
LAST_IP_FILE = "last_ip.txt"
