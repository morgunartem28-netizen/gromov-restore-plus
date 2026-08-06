# REPORT — GROMOV Restore+ 1.4.3

**Дата:** 2026-08-06  
**Release URL:** https://github.com/morgunartem28-netizen/gromov-restore-plus/releases/tag/1.4.3

## Что вошло

1. **Single-active install** — одна установка за раз, защита от параллельных worker-потоков.
2. **Cancel TOCTOU** — отмена больше не затирается `clear_cancel()`.
3. **USB off UI** — `list_usb_devices` только в background, окно отзывчиво при старте.
4. **Async icons** — ThreadPool + LRU, выбор приложения без microfreeze.
5. **Catalog SoT** — единое состояние в `CatalogController`.
6. **UX** — короче 2FA, toast/meta при busy-other-app.

## Tests

| Проверка | Результат |
|---------|-----------|
| `compileall src` | OK |
| `unittest discover -s tests` | **86 OK** |
| Smoke PYZ + launch | OK (build_release.ps1) |

## Build

| Параметр | Значение |
|---------|----------|
| Время сборки | ~150 с |
| SHA256 (подписанный Setup) | `a872516ce78869d7b6759c102028c245afa4e6d1af67085b8a9da2ab87b1b074` |
| Authenticode | `CN=GROMOV Restore` (self-signed, Status=UnknownError) |

## Release notes

🚀 Что нового в 1.4.3

— 🔒 Одна установка за раз — нельзя запустить несколько установок параллельно.  
— ⚡ Интерфейс не зависает при проверке USB и нажатии «Установить».  
— 📊 Исправлена отмена установки и отображение прогресса загрузки.  
— 🖼 Быстрее подгружаются иконки при выборе приложения.

Спасибо, что пользуетесь **GROMOV Restore+**! 💙
