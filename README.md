# GROMOV Restore+

Восстановление приложений App Store на iPhone (ВКонтакте, MAX, Авито, Почта Mail.ru).

**Поддержка:** Telegram [@gromov_restore](https://t.me/gromov_restore)

## Для пользователя

1. Установите **GROMOV-RestorePlus-Setup.exe** из папки `dist`
2. При установке отметьте «Установить драйверы Apple»
3. Запустите программу → войдите в Apple ID → подключите iPhone → выберите приложение

Данные хранятся в `%LOCALAPPDATA%\GROMOV\RestorePlus`

## Сборка

Полная сборка (PyInstaller + копирование `tools\` и `drivers\` в `dist` + Inno Setup):

```bat
build_release.bat
```

Не запускайте только PyInstaller/Inno без `build\build_release.ps1` — иначе в установщик не попадут `tools` и `drivers`.

Результат: `dist\GROMOV-RestorePlus-Setup.exe`

