@echo off
REM Сборка .exe под Windows. Запускать из этой папки.
pip install -r requirements.txt pyinstaller
pyinstaller --noconsole --onefile --name Messenger client.py
echo.
echo Готово: dist\Messenger.exe
pause
