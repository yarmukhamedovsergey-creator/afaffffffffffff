"""
Клиент личного мессенджера (Windows, customtkinter).

Перед сборкой заполните SECRET_KEY тем же значением, что и на сервере.
Сборка: pyinstaller --noconsole --onefile --name Messenger client.py
"""

import queue
import threading
import time

import customtkinter as ctk
import requests

# ----------------------------- Настройки --------------------------------

SERVER_URL = "https://mybotmessenger1234.bothost.tech"
SECRET_KEY = "ВСТАВЬ_ТОТ_ЖЕ_КЛЮЧ_ЧТО_НА_СЕРВЕРЕ"

POLL_TIMEOUT = 35          # чуть больше серверного лимита в 30 сек
RECONNECT_DELAY = 3        # пауза перед переподключением при ошибке
MONO_FONT = ("Consolas", 13)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class MessengerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Messenger")
        self.geometry("760x600")
        self.minsize(480, 400)

        self.last_id = 0
        self.ui_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()

        self._build_ui()
        self._ask_username()

        # Фоновый поток long polling
        threading.Thread(target=self._poll_loop, daemon=True).start()

        # Раз в 100 мс забираем события из потока в UI
        self.after(100, self._drain_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --------------------------- Интерфейс ------------------------------

    def _build_ui(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Верхняя панель: статус соединения
        self.status_label = ctk.CTkLabel(
            self, text="Подключение...", anchor="w",
            font=MONO_FONT, text_color="#8b949e",
        )
        self.status_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))

        # История чата. Textbox остаётся "normal", чтобы текст можно было
        # выделять и копировать; редактирование блокируем перехватом клавиш.
        self.history = ctk.CTkTextbox(
            self, font=MONO_FONT, wrap="word",
            corner_radius=12, fg_color="#16181d",
            border_color="#2a2f36", border_width=1,
        )
        self.history.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self.history.bind("<Key>", self._block_editing)
        self._history_len = "1.0"

        # Нижняя панель: поле ввода + кнопка
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        bottom.grid_columnconfigure(0, weight=1)

        self.input_box = ctk.CTkTextbox(
            bottom, height=64, font=MONO_FONT, wrap="word",
            corner_radius=12, fg_color="#16181d",
            border_color="#2a2f36", border_width=1,
        )
        self.input_box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        # Enter = отправить, Shift+Enter = перенос строки
        self.input_box.bind("<Return>", self._on_enter)
        self.input_box.bind("<Shift-Return>", lambda e: None)  # стандартный перенос

        self.send_button = ctk.CTkButton(
            bottom, text="➤", width=52, height=64,
            corner_radius=12, font=("Segoe UI Emoji", 18),
            command=self.send_message,
        )
        self.send_button.grid(row=0, column=1)

        hint = ctk.CTkLabel(
            self, text="Enter — отправить · Shift+Enter — новая строка",
            font=(MONO_FONT[0], 10), text_color="#586069",
        )
        hint.grid(row=3, column=0, sticky="w", padx=14, pady=(0, 6))

    def _ask_username(self) -> None:
        dialog = ctk.CTkInputDialog(text="Ваше имя в чате:", title="Вход")
        name = dialog.get_input()
        self.username = (name or "anon").strip() or "anon"
        self.title(f"Messenger — {self.username}")

    # --------------------- Защита истории от правок ----------------------

    def _block_editing(self, event):
        # Разрешаем только навигацию и Ctrl-комбинации (копирование и т.п.)
        nav = {"Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next"}
        if event.keysym in nav or (event.state & 0x4):  # 0x4 = Control
            return None
        return "break"

    # --------------------------- Отправка --------------------------------

    def _on_enter(self, event):
        self.send_message()
        return "break"  # не вставлять перенос строки

    def send_message(self) -> None:
        text = self.input_box.get("1.0", "end-1c").strip()
        if not text:
            return
        self.input_box.delete("1.0", "end")
        payload = {"sender": self.username, "text": text}
        # Отправляем в потоке, чтобы окно не подвисало
        threading.Thread(target=self._send_worker, args=(payload,), daemon=True).start()

    def _send_worker(self, payload: dict) -> None:
        try:
            resp = requests.post(
                f"{SERVER_URL}/api/send",
                json=payload,
                headers={"X-Secret-Key": SECRET_KEY},
                timeout=10,
            )
            if resp.status_code == 401:
                self.ui_queue.put(("status", "❌ 401: неверный SECRET_KEY"))
            elif resp.ok:
                # Своё сообщение покажет поллер, но подстрахуемся от потери:
                msg = resp.json()
                self.ui_queue.put(("status", "● Онлайн"))
            else:
                self.ui_queue.put(("status", f"⚠ Ошибка отправки: {resp.status_code}"))
        except requests.RequestException:
            self.ui_queue.put(("status", "⚠ Нет соединения при отправке"))

    # ------------------------- Long polling ------------------------------

    def _poll_loop(self) -> None:
        headers = {"X-Secret-Key": SECRET_KEY}
        while not self.stop_event.is_set():
            try:
                resp = requests.get(
                    f"{SERVER_URL}/api/get",
                    params={"last_id": self.last_id},
                    headers=headers,
                    timeout=POLL_TIMEOUT,
                )
                if resp.status_code == 401:
                    self.ui_queue.put(("status", "❌ 401: проверьте SECRET_KEY"))
                    time.sleep(RECONNECT_DELAY)
                    continue
                resp.raise_for_status()
                self.ui_queue.put(("status", "● Онлайн"))
                for msg in resp.json().get("messages", []):
                    self.ui_queue.put(("message", msg))
            except requests.RequestException:
                self.ui_queue.put(("status", "⚠ Нет соединения, переподключение..."))
                self.stop_event.wait(RECONNECT_DELAY)

    # --------------------- Мост поток -> интерфейс -----------------------

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, data = self.ui_queue.get_nowait()
                if kind == "message":
                    self._append_message(data)
                elif kind == "status":
                    self.status_label.configure(text=data)
        except queue.Empty:
            pass
        if not self.stop_event.is_set():
            self.after(100, self._drain_queue)

    def _append_message(self, msg: dict) -> None:
        self.last_id = max(self.last_id, msg["id"])
        ts = time.strftime("%H:%M", time.localtime(msg["ts"]))
        self.history.insert("end", f"[{ts}] {msg['sender']}:\n{msg['text']}\n\n")
        self.history.see("end")

    def _on_close(self) -> None:
        self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    MessengerApp().mainloop()