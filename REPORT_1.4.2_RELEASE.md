# REPORT — GROMOV Restore+ 1.4.2

**Дата:** 2026-08-04  
**Репозиторий:** morgunartem28-netizen/gromov-restore-plus  
**Статус:** опубликован  
**Release URL:** https://github.com/morgunartem28-netizen/gromov-restore-plus/releases/tag/1.4.2

## Что вошло

1. **Прогресс загрузки** — опрос `*.ipa.tmp` (ipatool пишет во временный файл до rename в `.ipa`), чтобы полоска не «зависала» на ~15% во время скачивания (`install_service.py` + `tests/test_install_progress.py`).
2. **Облако Mail.ru** — `mailru-cloud`, appId `696551382`, иконка `assets/icons/mailru-cloud.png`.
3. **Почта Mail.ru** — без изменений: `mailru` / appId `511310430` (фикс ID облака vs почты сохранён в `ConfigManager._APP_ID_FIXES`).
4. **Упаковка 1.4.1** — сохранены `hiddenimports` для всех `src/*.py` (включая `version`) и smoke-gate в `build_release.ps1`.

## Audit (spot-check)

| Область | Результат |
|--------|-----------|
| JSON `config/*.json` | OK |
| mailru (Почта) | `511310430`, icon `mailru.png` |
| mailru-cloud (Облако) | `696551382`, icon `mailru-cloud.png` present |
| tools_lock vs dist tools | ios / ipatool SHA совпали |
| Smoke PYZ | `version`, `help_dialog`, `update_checker`, `tool_integrity` — OK |
| Smoke launch | exe жив ≥5 с — OK |

## Tests

| Проверка | Результат |
|---------|-----------|
| `python -m compileall src` | OK |
| Import smoke | OK, `APP_VERSION=1.4.2` |
| `pytest tests` | **54 passed** |

## Build

| Параметр | Значение |
|---------|----------|
| Версия | `1.4.2` (`src/version.py`, `installer.iss`) |
| Скрипт | `build/build_release.ps1` |
| Smoke PYZ | OK (модуль `version` внутри) |
| Smoke launch | OK |
| SHA256 (после подписи) | `b7925044175f78483014f7e0c6abb95027f2153546d9279de896ca8f0c37db86` |
| Authenticode | Подписан `CN=GROMOV Restore` (Status=`UnknownError` — цепочка self-signed не в Trusted Root; подпись присутствует) |

## Update channel

`release/version.json`:

- version: `1.4.2`
- setup_url: GitHub Releases `…/download/1.4.2/GROMOV-RestorePlus-Setup.exe`
- sha256: совпадает с подписанным Setup

## Release notes (тело GitHub Release)

```
🚀 Что нового в 1.4.2

— 📊 Исправлено отображение прогресса загрузки — полоска больше не «зависает» на 15%.
— ☁️ Добавлено приложение **Облако Mail.ru**.

Спасибо, что пользуетесь **GROMOV Restore+**! 💙
```

## Файлы релиза

- `GROMOV-RestorePlus-Setup.exe` (GitHub Release asset)
- `release/version.json` (main)

## Заключение

Замороженный пакет содержит модуль `version`; smoke-gate пройден; Setup подписан; манифест обновлён. **1.4.2 готов к публикации.**
