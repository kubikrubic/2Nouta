# Сборка одного автономного файла dist\2Nouta.exe (Windows, консольное приложение).
# Нужен Python 3 с python.org (вместе с ним ставится Tkinter и лаунчер py).
# Перед сборкой нужны данные каталога: python fetch_data.py (папка data попадёт внутрь exe).
# Иконка exe — icon.ico из папки проекта.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Не удалось создать .venv. Установите Python с python.org." }
}

if (-not (Test-Path "data\models.json")) { throw "Нет data\models.json. Сначала запустите: python fetch_data.py" }

& $python -m pip install --disable-pip-version-check --quiet pyinstaller pillow
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить PyInstaller и Pillow." }

& $python -m PyInstaller --noconfirm --clean --onefile --console --name 2Nouta --icon icon.ico --add-data "data;data" main.py
if ($LASTEXITCODE -ne 0) { throw "Сборка не удалась." }

Write-Host "Готово: $PSScriptRoot\dist\2Nouta.exe"
