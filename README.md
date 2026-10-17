# Messenger Project

Всё в одной папке, один общий requirements.txt.

## Сервер (BotHost)
Файлы: `main.py`, `requirements.txt`, `Dockerfile`

1. Загрузите эти три файла на BotHost.
2. В панели BotHost задайте переменные:
   - `SECRET_KEY` — длинная случайная строка (ключ API)
   - `BOT_TOKEN` — токен бота от @BotFather (команда /status)
   - `PORT` — подставляется автоматически (по умолчанию 3000)
3. Проверка: https://mybotmessenger1234.bothost.tech/health -> {"status": "ok"}

## Клиент (Windows .exe)
Файлы: `client.py`, `build_exe.bat`

1. В `client.py` вставьте тот же `SECRET_KEY`, что на сервере.
2. Запустите `build_exe.bat` — он сам поставит зависимости и соберёт exe.
3. Готовый файл: `dist\Messenger.exe`.
