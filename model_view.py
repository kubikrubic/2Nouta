import io
import tkinter as tk
import webbrowser

from PIL import Image, ImageTk

PHOTO_SIZE = (560, 350)
NO_DATA = "нет данных"
SPEC_FIELDS = [
    ("years", "Годы выпуска"),
    ("body", "Кузов"),
    ("engine", "Двигатель"),
    ("power", "Мощность"),
    ("gearbox", "Коробка"),
    ("drive", "Привод"),
    ("trunk", "Объём багажника"),
]


def load_photo(data):
    """Открывает фото из байтов и уменьшает под окно. Работает в любом потоке, в отличие от Tk."""
    image = Image.open(io.BytesIO(data))
    image.thumbnail(PHOTO_SIZE)
    return image.convert("RGB")


class ModelView(tk.Frame):
    """Фото модели с переключением, подпись автора и лицензии и характеристики. Один и тот же на сервере и клиенте."""

    def __init__(self, master):
        super().__init__(master)
        self.photos = []  # ImageTk.PhotoImage нужно хранить, иначе Tk покажет пустое место
        self.credits = []
        self.index = 0
        self.article_url = None

        self.title_label = tk.Label(self, text="", font=("Arial", 16, "bold"), wraplength=1000)
        self.title_label.pack(pady=5)

        self.body = tk.Frame(self)
        left = tk.Frame(self.body)
        left.pack(side=tk.LEFT, anchor=tk.N, padx=10)

        photo_frame = tk.Frame(left, width=PHOTO_SIZE[0], height=PHOTO_SIZE[1], bg="#e8e8e8")
        photo_frame.pack_propagate(False)
        photo_frame.pack()
        self.photo_label = tk.Label(photo_frame, bg="#e8e8e8", fg="gray", font=("Arial", 12))
        self.photo_label.pack(expand=True, fill=tk.BOTH)

        navigation = tk.Frame(left)
        navigation.pack(pady=4)
        self.previous_button = tk.Button(navigation, text="◀", width=4, command=lambda: self.show_photo(self.index - 1))
        self.previous_button.pack(side=tk.LEFT)
        self.counter_label = tk.Label(navigation, text="", width=10)
        self.counter_label.pack(side=tk.LEFT)
        self.next_button = tk.Button(navigation, text="▶", width=4, command=lambda: self.show_photo(self.index + 1))
        self.next_button.pack(side=tk.LEFT)

        self.credit_label = tk.Label(left, text="", font=("Arial", 8), fg="gray", wraplength=PHOTO_SIZE[0],
                                     justify=tk.LEFT, cursor="hand2")
        self.credit_label.pack(anchor=tk.W)
        self.credit_label.bind("<Button-1>", lambda event: self.open_url(self.current_source()))

        self.specs = tk.Frame(self.body)
        self.specs.pack(side=tk.LEFT, anchor=tk.N, fill=tk.BOTH, expand=True, padx=(0, 10))
        self.specs.columnconfigure(1, weight=1)
        self.spec_labels = {}
        for row, (key, caption) in enumerate(SPEC_FIELDS):
            caption_label = tk.Label(self.specs, text=caption + ":", font=("Arial", 10, "bold"))
            caption_label.grid(row=row, column=0, sticky=tk.NW, pady=3)
            value_label = tk.Label(self.specs, text="", font=("Arial", 10), wraplength=200, justify=tk.LEFT)
            value_label.grid(row=row, column=1, sticky=tk.NW, padx=(8, 0), pady=3)
            self.spec_labels[key] = value_label
        self.article_label = tk.Label(self.specs, text="", font=("Arial", 8), fg="gray", cursor="hand2",
                                      wraplength=300, justify=tk.LEFT)
        self.article_label.grid(row=len(SPEC_FIELDS), column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        self.article_label.bind("<Button-1>", lambda event: self.open_url(self.article_url))
        # перенос строк по фактической ширине колонки, чтобы текст не уходил за край окна
        self.specs.bind("<Configure>", self.fit_specs)

    def fit_specs(self, event):
        caption_width = max(self.specs.grid_bbox(0, row)[2] for row in range(len(SPEC_FIELDS)))
        value_width = max(150, event.width - caption_width - 12)
        for label in self.spec_labels.values():
            label.config(wraplength=value_width)
        self.article_label.config(wraplength=max(150, event.width - 4))

    def show_message(self, text, error=False):
        """Убирает показанную модель целиком и выводит только текст: «Загрузка…» или ошибку."""
        self.body.pack_forget()
        self.photos = []
        self.credits = []
        self.photo_label.config(image="", text="")
        self.title_label.config(text=text, fg="firebrick" if error else "black")

    def show_model(self, model, images):
        """images — картинки PIL из load_photo() по порядку model["photos"], None вместо неоткрывшихся."""
        specs = model.get("specs") or {}
        self.title_label.config(text=model.get("name", ""), fg="black")
        for key, label in self.spec_labels.items():
            value = specs.get(key)
            label.config(text=value if isinstance(value, str) and value else NO_DATA)

        self.article_url = model.get("article")
        self.article_label.config(text=f"Характеристики: Википедия, {self.article_url}" if self.article_url else "")

        self.photos = [ImageTk.PhotoImage(image) if image is not None else None for image in images]
        self.credits = list(model.get("photos") or [])[:len(self.photos)]
        self.show_photo(0)
        self.body.pack(fill=tk.BOTH, expand=True)

    def show_photo(self, index):
        if not self.photos:
            self.photo_label.config(image="", text="Нет фото")
            self.counter_label.config(text="")
            self.credit_label.config(text="")
            self.previous_button.config(state=tk.DISABLED)
            self.next_button.config(state=tk.DISABLED)
            return
        self.index = index % len(self.photos)
        photo = self.photos[self.index]
        if photo is None:
            self.photo_label.config(image="", text="Фото не загрузилось")
        else:
            self.photo_label.config(image=photo, text="")
        self.counter_label.config(text=f"{self.index + 1} из {len(self.photos)}")
        state = tk.NORMAL if len(self.photos) > 1 else tk.DISABLED
        self.previous_button.config(state=state)
        self.next_button.config(state=state)

        credit = self.credits[self.index] if self.index < len(self.credits) else {}
        author = credit.get("author") or "автор неизвестен"
        license_name = credit.get("license") or "лицензия не указана"
        source = credit.get("source") or ""
        self.credit_label.config(text=f"Фото: {author}, {license_name}\n{source}")

    def current_source(self):
        if self.index < len(self.credits):
            return self.credits[self.index].get("source")
        return None

    def open_url(self, url):
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)
