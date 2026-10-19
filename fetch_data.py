"""Скачивает каталог Lada: характеристики с ru.wikipedia.org и фото с Wikimedia Commons.

Результат: data/models.json и data/photos/<id>/<n>.jpg. Запуск: python fetch_data.py
Характеристики берутся только из статей; чего нет в статье, записывается как null.
"""
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

USER_AGENT = "2NoutaLadaCatalog/1.0 (educational project; contact: YOUR_EMAIL@example.com)"
WIKI_API = "https://ru.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
PAUSE = 1.0
PHOTO_WIDTH = 960  # стандартный размер превью Wikimedia, ближайший к 1000 px
MIN_PHOTOS = 3
MAX_PHOTOS = 5
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# commons: категории Commons или поисковые запросы ("search:...") по файлам
MODELS = [
    {"id": "granta", "name": "Lada Granta", "article": "Lada Granta", "keyword": "granta",
     "commons": ["Category:Lada Granta FL sedan", "Category:Lada Granta FL liftback",
                 "Category:Lada Granta FL hatchback"]},
    {"id": "vesta", "name": "Lada Vesta", "article": "Lada Vesta", "keyword": "vesta",
     "commons": ["Category:Lada Vesta", "Category:Lada Vesta SW"]},
    {"id": "niva_legend", "name": "Lada Niva Legend", "article": "Lada Niva Legend", "keyword": "niva legend",
     "commons": ['search:intitle:"Niva Legend"']},
    {"id": "niva_travel", "name": "Lada Niva Travel", "article": "Lada Niva Travel", "keyword": "niva travel",
     "commons": ["Category:Lada Niva Travel"]},
    {"id": "largus", "name": "Lada Largus", "article": "Lada Largus", "keyword": "largus",
     "commons": ["Category:Lada Largus"]},
    {"id": "iskra", "name": "Lada Iskra", "article": "Lada Iskra", "keyword": "iskra",
     "commons": ["Category:Lada Iskra"]},
]

# поля карточки {{Автомобиль}} для каждой характеристики
INFOBOX_FIELDS = {
    "years": ["годы производства"],
    "body": ["тип кузова"],
    "layout": ["компоновка"],
    "wheels": ["колёсная формула"],
    "engine": ["двигатель"],
    "gearbox": ["кпп", "трансмиссия"],
    "trunk": ["объём багажника", "объем багажника"],
}
NOT_EXTERIOR = ["interior", "innenraum", "salon", "dashboard", "kombiinstrument", "cockpit", "motorraum",
                "engine", "motor", "seats", "trunk", "boot", "logo", "badge", "emblem", "wheel", "detail",
                "steering", "cabin", "салон", "двигател", "багажник", "приборн", "assembly", "factory",
                "museum", "crash", "competition", "rally", "police", "ambulance", "tram"]
VIEWS = ["front", "rear", "side"]


def request(url, data=None, attempts=3):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        time.sleep(PAUSE * attempt)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code != 429 and error.code < 500 or attempt == attempts:
                raise
        except (urllib.error.URLError, OSError):
            if attempt == attempts:
                raise
        print(f"  повтор запроса ({attempt} из {attempts - 1})")


def api(url, **params):
    params.update(format="json", formatversion="2")
    # длинный текст для expandtemplates не влезает в адрес, поэтому всё отправляется POST
    result = json.loads(request(url, data=params))
    if "error" in result:
        raise RuntimeError(f"{url}: {result['error'].get('info')}")
    return result


def api_pages(url, max_requests=5, **params):
    """Запрос с generator: собирает страницы из всех продолжений в словарь по названию."""
    pages = {}
    extra = {}
    for _ in range(max_requests):
        result = api(url, action="query", **params, **extra)
        for page in result.get("query", {}).get("pages", []):
            merged = pages.setdefault(page["title"], {})
            for key, value in page.items():
                if key not in merged or not merged[key]:
                    merged[key] = value
        if "continue" not in result:
            break
        extra = result["continue"]
    return pages


# ---------- разбор вики-текста ----------

def find_templates(text, names):
    """Тексты шаблонов {{Имя ...}} с указанными именами (без внешних скобок)."""
    found = []
    start = text.find("{{")
    while start >= 0:
        depth, position = 0, start
        while position < len(text):
            if text.startswith("{{", position):
                depth += 1
                position += 2
            elif text.startswith("}}", position):
                depth -= 1
                position += 2
                if depth == 0:
                    break
            else:
                position += 1
        body = text[start + 2:position - 2]
        name = re.split(r"[|\n]", body, maxsplit=1)[0].strip().lower()
        if name in names:
            found.append(body)
        start = text.find("{{", start + 2)
    return found


def split_params(body):
    """Параметры шаблона: {"имя": "значение"}; "|" внутри {{ }} и [[ ]] не разделяет."""
    parts, current = [], ""
    braces = links = 0
    position = 0
    while position < len(body):
        pair = body[position:position + 2]
        if pair in ("{{", "}}", "[[", "]]"):
            braces += {"{{": 1, "}}": -1}.get(pair, 0)
            links += {"[[": 1, "]]": -1}.get(pair, 0)
            current += pair
            position += 2
            continue
        if body[position] == "|" and braces == 0 and links == 0:
            parts.append(current)
            current = ""
        else:
            current += body[position]
        position += 1
    parts.append(current)

    params = {}
    for part in parts[1:]:
        key, sign, value = part.partition("=")
        if sign and "{{" not in key and "[[" not in key:
            params[key.strip().lower()] = value.strip()
    return params


def remove_refs(text):
    text = re.sub(r"<ref[^>/]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def clean(text):
    """Превращает раскрытый вики-текст и HTML в обычный текст. Строки разделены \\n."""
    text = remove_refs(text)
    text = re.sub(r"\[\[(?:Категория|Category|Файл|File|Изображение):[^\]]*\]\]", "", text)
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", text)
    text = re.sub(r'<span[^>]*title="([^"]*)"[^>]*>([^<]*)</span>', r"\2 (\1)", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<sup>3</sup>", "³", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"'{2,}", "", text)
    text = html.unescape(text)
    text = text.translate({0xA0: " ", 0x202F: "", 0x2009: " ", 0x2011: "-"})
    lines = [re.sub(r"\s+", " ", line).strip(" ,;") for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def expand(values, title):
    """Раскрывает шаблоны в нескольких значениях за один запрос к API."""
    if not values:
        return []
    marker = "@@2NOUTA{}@@"
    text = "".join(marker.format(index) + value for index, value in enumerate(values))
    result = api(WIKI_API, action="expandtemplates", text=text, prop="wikitext", title=title)
    expanded = result["expandtemplates"]["wikitext"]
    parts = re.split(r"@@2NOUTA\d+@@", expanded)[1:]
    return parts if len(parts) == len(values) else [""] * len(values)


def table_rows(expanded):
    """Строки HTML-карточки: (заголовок, {подпись: значение})."""
    above = re.search(r'class="infobox-above[^"]*"[^>]*>(.*?)</th>', expanded, flags=re.S)
    rows = {}
    for label, value in re.findall(r"<th scope=\"row\"[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", expanded, flags=re.S):
        rows[clean(label).lower()] = clean(value).replace("\n", ", ")
    return (clean(above.group(1)) if above else ""), rows


def first_field(infoboxes, names):
    for params in infoboxes:
        for name in names:
            value = remove_refs(params.get(name, "")).strip()
            if value:
                return value
    return ""


def describe_engines(raw, title):
    templates = find_templates(raw, {"двигатель"})
    if not templates:
        text = clean(raw)
        return (text.replace("\n", "; ") or None), None
    engines, powers = [], []
    for expanded in expand(["{{" + body + "}}" for body in templates], title):
        name, rows = table_rows(expanded)
        name = re.sub(r"\s*\([\d,.]+ л\. ?с\.\)$", "", name)  # мощность и так показана отдельно
        details = ", ".join(rows[key] for key in ("тип", "объём") if rows.get(key))
        engines.append(f"{name} ({details})" if details and name else name or details)
        # в статье бывает «78 кВт (106 л. с.)», и шаблон дописывает ещё одно «кВт»
        power = re.sub(r"(л\. ?с\.\)) кВт", r"\1", rows.get("максимальная мощность", ""))
        if power:
            powers.append(f"{name}: {power}" if name else power)
    return join_unique(engines), join_unique(powers)


def join_unique(items):
    unique = [item for index, item in enumerate(items) if item and item not in items[:index]]
    return "; ".join(unique) or None


def describe_gearbox(raw, title):
    templates = find_templates(raw, {"кпп"})
    if not templates:
        return clean(raw).replace("\n", "; ") or None
    boxes = []
    for expanded in expand(["{{" + body + "}}" for body in templates], title):
        name, rows = table_rows(expanded)
        name = re.sub(r"\s+-ступ\.", "", name)  # у вариатора число ступеней пустое
        kind = rows.get("тип", "")
        steps = rows.get("число ступеней", "")
        text = ", ".join(part for part in (kind, f"{steps}-ступ." if steps else "") if part)
        if name.replace(" ", "") in (kind.replace(" ", ""), text.replace(",", "").replace(" ", "")):
            name = ""
        boxes.append(f"{text} ({name})" if text and name else text or name)
    return join_unique(boxes)


def describe_drive(layout, wheels):
    layout = layout.lower()
    if "полноприводн" in layout:
        drive = "полный"
    elif "переднеприводн" in layout:
        drive = "передний"
    elif "заднеприводн" in layout:
        drive = "задний"
    else:
        drive = ""
    wheels = wheels.replace(" ", "")
    return ", ".join(part for part in (drive, wheels) if part) or None


def section_at(text, position):
    headings = re.findall(r"^=+\s*(.*?)\s*=+\s*$", text[:position], flags=re.M)
    return clean(headings[-1]) if headings else ""


def find_trunk(article_text, infobox_text):
    """Объём багажника: параметр карточки, строка таблицы или фраза в тексте статьи."""
    match = re.search(r"\|\s*объ[её]м багажника\s*=\s*([^|\n}]+)", infobox_text, flags=re.I)
    if match and clean(match.group(1)):
        return clean(match.group(1))

    text = remove_refs(article_text)
    match = re.search(r"^\|\s*(Объ[её]м багажника[^|\n]*)\|\|(.+)$", text, flags=re.M | re.I)
    if match:
        unit = "л" if re.search(r",\s*л\b", match.group(1)) else ""
        cells = [re.sub(r"^[^|]*=\s*\"?\d+\"?\s*\|", "", cell).strip() for cell in match.group(2).split("||")]
        value = " / ".join(clean(cell) for cell in cells if clean(cell))
        if value:
            section = section_at(text, match.start())
            return f"{value} {unit}".strip() + (f" ({section})" if section else "")

    pattern = r"[^.\n]*объ[её]м\w* багажн\w*[^.\n]*?\d[^.\n]*?\s(?:л|литр\w*)\b[^.\n]*\.?"
    match = re.search(pattern, text, flags=re.I)
    if match:
        sentence = clean(match.group(0))
        section = section_at(text, match.start())
        return f"{section}: {sentence}" if section else sentence
    return None


def fetch_specs(model):
    result = api(WIKI_API, action="query", prop="revisions", rvprop="content", rvslots="main",
                 titles=model["article"], redirects=1)
    page = result["query"]["pages"][0]
    if "missing" in page:
        raise RuntimeError(f"статья «{model['article']}» не найдена")
    title = page["title"]
    text = page["revisions"][0]["slots"]["main"]["content"]

    infobox_texts = find_templates(text, {"автомобиль"})
    infoboxes = [split_params(body) for body in infobox_texts]
    # общая карточка модели, затем карточки поколений от новых к старым
    infoboxes = infoboxes[:1] + infoboxes[1:][::-1]
    raw = {key: first_field(infoboxes, names) for key, names in INFOBOX_FIELDS.items()}

    simple = ["years", "body", "layout", "wheels"]
    expanded = dict(zip(simple, (clean(value) for value in expand([raw[key] for key in simple], title))))
    engine, power = describe_engines(raw["engine"], title)
    specs = {
        "years": expanded["years"].replace("\n", "; ") or None,
        "body": expanded["body"].replace("\n", "; ") or None,
        "engine": engine,
        "power": power,
        "gearbox": describe_gearbox(raw["gearbox"], title),
        "drive": describe_drive(expanded["layout"], expanded["wheels"]),
        "trunk": clean(raw["trunk"]) or find_trunk(text, "\n".join(infobox_texts)),
    }
    photo = first_field(infoboxes[:1], ["фото", "изображение"])
    return title, specs, photo


# ---------- фото ----------

def is_free_license(meta):
    license_code = meta.get("License", {}).get("value", "").lower()
    short_name = meta.get("LicenseShortName", {}).get("value", "").lower()
    if re.search(r"\b(nc|nd)\b", license_code + " " + short_name):
        return False
    if license_code in ("cc0", "pd") or license_code.startswith("pd-"):
        return True
    if re.fullmatch(r"cc-by(-sa)?-[\d.]+(-[a-z]+)?", license_code):
        return True
    return short_name in ("public domain", "cc0") or bool(re.fullmatch(r"cc by(-sa)? [\d.]+( [a-z]+)?", short_name))


def text_of(meta, key):
    return clean(meta.get(key, {}).get("value", ""))


def photo_candidates(model, infobox_photo):
    imageinfo = dict(prop="imageinfo", iiprop="url|size|mime|extmetadata", iiurlwidth=PHOTO_WIDTH,
                     iiextmetadatafilter="License|LicenseShortName|LicenseUrl|Artist|Credit")
    pages = {}
    if infobox_photo:
        name = infobox_photo if ":" in infobox_photo else "File:" + infobox_photo
        pages.update(api_pages(COMMONS_API, titles=name, **imageinfo))
    first_title = next(iter(pages), None)
    for source in model["commons"]:
        if source.startswith("search:"):
            pages.update(api_pages(COMMONS_API, generator="search", gsrsearch=source[7:], gsrnamespace=6,
                                   gsrlimit=50, **imageinfo))
        else:
            pages.update(api_pages(COMMONS_API, generator="categorymembers", gcmtitle=source, gcmtype="file",
                                   gcmlimit=100, **imageinfo))

    candidates = []
    for title, page in pages.items():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lower = title.lower()
        if info.get("mime") not in ("image/jpeg", "image/png") or not info.get("thumburl"):
            continue
        if info.get("width", 0) < PHOTO_WIDTH or info["width"] < info.get("height", 0) * 1.2:
            continue
        if not is_free_license(meta) or "lada.ru" in (meta.get("Credit", {}).get("value", "") +
                                                     meta.get("Artist", {}).get("value", "")).lower():
            continue
        if title != first_title and (model["keyword"] not in lower or any(word in lower for word in NOT_EXTERIOR)):
            continue
        year = re.match(r"file:(\d{4})\b", lower)
        candidates.append({
            "title": title,
            "first": title == first_title,
            "year": int(year.group(1)) if year else 0,
            "url": info["thumburl"].split("?")[0],
            "author": text_of(meta, "Artist") or text_of(meta, "Credit") or "неизвестен",
            "license": text_of(meta, "LicenseShortName"),
            "license_url": meta.get("LicenseUrl", {}).get("value") or None,
            "source": info.get("descriptionurl"),
        })
    return candidates


def choose_photos(candidates):
    """Фото из карточки статьи, затем по кругу вид спереди, сзади, сбоку; новые годы раньше."""
    candidates = sorted(candidates, key=lambda photo: (not photo["first"], -photo["year"], photo["title"]))
    # «... front.jpg», «... front1.jpg» и «... front (2).jpg» обычно снимки одной машины
    same_car = {photo["title"]: re.sub(r"\s*\(?\d*\)?\.\w+$", "", photo["title"].lower()) for photo in candidates}
    unique, seen = [], set()
    for photo in candidates:
        if same_car[photo["title"]] not in seen:
            seen.add(same_car[photo["title"]])
            unique.append(photo)
    candidates = unique

    chosen = [photo for photo in candidates if photo["first"]][:1]
    while len(chosen) < MAX_PHOTOS:
        added = False
        for view in VIEWS:
            for photo in candidates:
                if photo not in chosen and view in photo["title"].lower():
                    chosen.append(photo)
                    added = True
                    break
            if len(chosen) == MAX_PHOTOS:
                break
        if not added:
            break
    for photo in candidates:
        if len(chosen) == MAX_PHOTOS:
            break
        if photo not in chosen:
            chosen.append(photo)
    return chosen


def save_photos(model_id, photos):
    folder = os.path.join(DATA_DIR, "photos", model_id)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    saved = []
    for number, photo in enumerate(photos, start=1):
        extension = os.path.splitext(photo["url"])[1].lower() or ".jpg"
        file_name = f"{number}{extension}"
        try:
            content = request(photo["url"])
        except OSError as error:
            print(f"  не скачано {photo['title']}: {error}")
            continue
        with open(os.path.join(folder, file_name), "wb") as file:
            file.write(content)
        saved.append({"file": file_name, "title": photo["title"], "author": photo["author"],
                      "license": photo["license"], "license_url": photo["license_url"], "source": photo["source"]})
        print(f"  фото {file_name}: {photo['title']} ({photo['license']}, {photo['author']})")
    return saved


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(DATA_DIR, exist_ok=True)
    result = {"fetched": date.today().isoformat(),
              "sources": "Характеристики: ru.wikipedia.org (CC BY-SA 4.0). Фото: commons.wikimedia.org.",
              "models": []}
    for model in MODELS:
        print(f"{model['name']}:")
        title, specs, infobox_photo = fetch_specs(model)
        for key, value in specs.items():
            print(f"  {key}: {value if value is not None else 'нет данных'}")
        photos = save_photos(model["id"], choose_photos(photo_candidates(model, infobox_photo)))
        if len(photos) < MIN_PHOTOS:
            print(f"  внимание: найдено только {len(photos)} фото")
        result["models"].append({
            "id": model["id"],
            "name": model["name"],
            "article": "https://ru.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
            "specs": specs,
            "photos": photos,
        })

    with open(os.path.join(DATA_DIR, "models.json"), "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(f"Сохранено: {os.path.join(DATA_DIR, 'models.json')}")


if __name__ == "__main__":
    main()
