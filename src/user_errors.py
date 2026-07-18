"""Map technical tool errors to short user-facing Russian messages."""
from __future__ import annotations


def friendly_error(exc: BaseException | str, *, domain: str = "Общая") -> tuple[str, str]:
    """Return (title, message)."""
    text = str(exc).strip()
    lower = text.lower()

    if domain == "Apple ID" or "apple" in lower or "auth" in lower or "login" in lower:
        if "2fa" in lower or "auth code" in lower or "verification" in lower:
            return "Apple ID", "Нужен код подтверждения с iPhone или Mac."
        if "password" in lower or "badlogin" in lower or "incorrect" in lower:
            return "Apple ID", "Неверный email или пароль Apple ID."
        if "disabled" in lower:
            return "Apple ID", "Неверный email или пароль Apple ID."
        if "rate" in lower or "429" in lower:
            return "Apple ID", "Apple временно ограничил вход. Подождите несколько минут."
        if "network" in lower or "connection" in lower or "timed out" in lower:
            return "Сеть", "Нет связи с Apple. Проверьте интернет и повторите."
        return "Apple ID", "Не удалось войти в Apple ID.\nПроверьте данные и попробуйте снова."

    if "disk" in lower or "места" in lower or "space" in lower:
        return "Диск", "Недостаточно места на диске.\nОсвободите место и повторите."

    if "device" in lower or "iphone" in lower or "udid" in lower or "usbmux" in lower:
        return (
            "iPhone",
            "iPhone не найден или недоступен.\n"
            "Проверьте кабель USB, нажмите «Доверять» и повторите.",
        )

    if "tunnel" in lower or "agent is not running" in lower:
        return (
            "iPhone",
            "Для этой версии iOS нужно дополнительное подключение.\n"
            "Переподключите кабель и повторите установку.",
        )

    if "eof" in lower:
        return (
            "iPhone",
            "Соединение оборвалось при передаче файла.\n"
            "Используйте оригинальный кабель и не отключайте iPhone.",
        )

    if "zip" in lower or "поврежд" in lower or "not a valid" in lower:
        return (
            "Файл IPA",
            "Файл приложения повреждён или скачан не полностью.\n"
            "Он будет удалён — нажмите «Повторить».",
        )

    if "license" in lower:
        return (
            "Лицензия",
            "У этого Apple ID нет лицензии на приложение.\n"
            "Войдите в аккаунт, с которого оно покупалось.",
        )

    if "cancel" in lower or "отмен" in lower:
        return "Отмена", "Операция отменена."

    # Strip huge go-ios dumps for the dialog body.
    short = text
    if "\n" in short and len(short) > 280:
        short = short.split("\n", 1)[0][:240]
    if len(short) > 320:
        short = short[:300] + "…"

    if domain == "Установка" or "install" in lower:
        return (
            "Установка",
            "Не удалось установить приложение.\n"
            "Проверьте подключение iPhone и повторите попытку.",
        )

    return domain, short or "Произошла ошибка. Повторите попытку."
