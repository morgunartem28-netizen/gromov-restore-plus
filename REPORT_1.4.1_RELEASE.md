# REPORT — GROMOV Restore+ 1.4.1

**Дата:** 2026-08-04  
**Репозиторий:** morgunartem28-netizen/gromov-restore-plus  
**Статус:** готов к публикации / опубликован после smoke-gate

## Корневая причина предыдущего 1.4.1

Удалённый релиз падал при старте:

`ModuleNotFoundError: No module named 'version'`

(`help_dialog.py` / `update_checker.py` / `main.py` импортируют `version`).

### Исправление

1. `build/GROMOV-RestorePlus.spec` — явный сбор **всех** `src/*.py` в `hiddenimports` (включая `version`).
2. `build/build_release.ps1` — smoke-gate **до** Inno:
   - извлечение `PYZ.pyz` из onedir EXE и проверка наличия `version`, `help_dialog`, `update_checker`, `tool_integrity`;
   - проверка `PYZ-00.toc`;
   - краткий запуск `GROMOV-RestorePlus.exe` (≥5 с без выхода / `ModuleNotFoundError` в `startup_crash.log`).

## Audit (spot-check)

| Область | Результат |
|--------|-----------|
| Update / install / Authenticode | `UpdateController` + SHA256 + `verify_setup_authenticode` |
| Auth / catalog search | без blockers |
| Virtual list + tab scroll-to-top | `_scroll_catalog_to_top` → `yview_moveto(0)` |
| Dark-only theme | `theme.py` всегда dark |
| Inno | `CloseApplications=yes`, `restartreplace` на Files |
| tools_lock vs dist tools | ios / ipatool SHA совпали |
| T-Bank icons | `tbank-*.png` на месте |

Стабильность-блокеров, мешающих релизу, не найдено (кроме уже закрытого `version` bundling).

## Tests

| Проверка | Результат |
|---------|-----------|
| `python -m compileall src` | OK |
| JSON `config/*.json` | OK |
| Import smoke (`version`, `help_dialog`, …) | OK, `APP_VERSION=1.4.1` |
| `pytest tests` | **47 passed** |

## Build

| Параметр | Значение |
|---------|----------|
| Версия | `1.4.1` (`src/version.py`, `installer.iss`) |
| Скрипт | `build/build_release.ps1` |
| Время сборки | ~62 с (PyInstaller + smoke + Inno) |
| Smoke PYZ | `version` / `help_dialog` / `update_checker` / `tool_integrity` — OK |
| Smoke launch | exe жив ≥5 с — OK |
| SHA256 (после подписи) | `13ed9594a6f664129eb058d9b79e0ff43d4b35252e894530fcd76cea844d0ac1` |
| Authenticode | Подписан `CN=GROMOV Restore` (Status=`UnknownError` — цепочка self-signed не в Trusted Root; подпись присутствует) |

## Update channel

`release/version.json`:

- version: `1.4.1`
- setup_url: GitHub Releases `…/download/1.4.1/GROMOV-RestorePlus-Setup.exe`
- sha256: совпадает с подписанным Setup

## Release notes (тело GitHub Release)

```
🚀 Что нового в обновлении

— ⚡ Ускорили работу приложения — теперь всё работает заметно быстрее и плавнее.
— 🏦 Добавили новое приложение **Т-Банка**.
— 🎨 Освежили дизайн интерфейса, сделав его современнее и удобнее.
— 🔧 Исправлена установка обновления и проверка целостности встроенных инструментов.

Спасибо, что пользуетесь **GROMOV Restore+**! 💙
```

## Файлы релиза

- `GROMOV-RestorePlus-Setup.exe` (GitHub Release asset)
- `release/version.json` (main)

## Заключение

Замороженный пакет содержит модуль `version`; smoke-gate пройден; Setup подписан; манифест обновлён. **1.4.1 готов к публикации.**
