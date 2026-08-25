# REPORT — GROMOV Restore+ 1.4.5

**Дата:** 2026-08-25  
**Release URL:** https://github.com/morgunartem28-netizen/gromov-restore-plus/releases/tag/1.4.5

## Что изменилось

2FA Apple **не отключается** — без кода App Store не отдаёт IPA.

Проблема «Apple не может отправить 2FA»: ipatool ходит в iTunes/Configurator API. Apple **часто не шлёт push/SMS** на этот вход. Ждать уведомление бесполезно.

**Новый сценарий:** пользователь сам берёт код на iPhone  
`Настройки → Apple ID → Вход и безопасность → Получить код проверки`  
и вводит email + пароль + 6 цифр одним заходом.

## Tests / Build

| Проверка | Результат |
|---------|-----------|
| unittest | **86 OK** |
| SHA256 | `7ba90e5f40e81e176ab2276dcbd93e5d3f37204dce0ec29194592b3fbf5dd8ac` |
| Authenticode | `CN=GROMOV Restore` (self-signed) |
