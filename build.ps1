# Сборка одного автономного файла dist\2Nouta.exe (Windows, консольное приложение).
# Нужен Python 3 с python.org (вместе с ним ставится Tkinter и лаунчер py).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Не удалось создать .venv. Установите Python с python.org." }
}

& $python -m pip install --disable-pip-version-check --quiet pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить PyInstaller." }

& $python -m PyInstaller --noconfirm --clean --onefile --console --name 2Nouta main.py
if ($LASTEXITCODE -ne 0) { throw "Сборка не удалась." }

Write-Host "Готово: $PSScriptRoot\dist\2Nouta.exe"
