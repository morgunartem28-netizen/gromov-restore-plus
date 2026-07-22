"""Map technical tool errors to short user-facing Russian messages."""
from __future__ import annotations


def friendly_error(exc: BaseException | str, *, domain: str = "Общая") -> tuple[str, str]:
    """Return (title, message)."""
    text = str(exc).strip()
    lower = text.lower()

    # Already crafted multi-line Russian guidance from our code — keep body intact.
    if "\n" in text and any(
        marker in lower
        for marker in (
            "подключ",
            "выберите",
            "повторите",
            "скачайте",
            "разблокир",
            "доверя",
            "кабел",
            "освободите",
        )
    ):
        title = domain if domain not in {"Общая", "Установка"} else "iPhone"
        if "ipa" in lower or "поврежд" in lower or "файл" in lower:
            title = "Файл IPA"
        elif "apple" in lower or "лиценз" in lower:
            title = "Apple ID"
        elif "мест" in lower or "диск" in lower:
            title = "Диск"
        elif "несколько" in lower:
            title = "Несколько iPhone"
        elif "отключ" in lower:
            title = "iPhone отключён"
        return title, text

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

    if "несколько" in lower or ("multiple" in lower and "device" in lower):
        return (
            "Несколько iPhone",
            "Подключено несколько iPhone по USB.\nВыберите устройство перед установкой.",
        )

    if any(
        token in lower
        for token in ("отключ", "unplug", "disconnect", "device not connected", "no device", "not found")
    ) and any(token in lower for token in ("iphone", "device", "usb", "udid")):
        return (
            "iPhone отключён",
            "iPhone отключён или недоступен по USB.\n"
            "Подключите кабель, разблокируйте телефон и нажмите «Доверять».",
        )

    if any(token in lower for token in ("locked", "lockdown", "password protected", "заблок")):
        return (
            "iPhone",
            "Разблокируйте iPhone и повторите установку.\n"
            "Экран блокировки мешает передаче по USB.",
        )

    if any(token in lower for token in ("trust", "pair", "pairing", "доверя")):
        return (
            "iPhone",
            "Нажмите «Доверять этому компьютеру» на iPhone и повторите.",
        )

    if any(
        token in lower
        for token in ("sign", "provision", "certificate", "codesign", "подпись", "сертификат")
    ):
        return (
            "Подпись",
            "Проблема с подписью приложения.\n"
            "Скачайте IPA заново под тем же Apple ID и повторите.",
        )

    if "device" in lower or "iphone" in lower or "udid" in lower or "usbmux" in lower:
        return (
            "iPhone",
            "iPhone по USB не найден или недоступен.\n"
            "Подключите кабель USB, разблокируйте, нажмите «Доверять» и повторите.\n"
            "Устройства только по Wi‑Fi не используются.",
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
