"""Install-related dialogs extracted from main (behavior unchanged)."""
from __future__ import annotations

from tkinter import messagebox

from security_utils import mask_email


def show_fairplay_launch_checklist(*, apple_account_email: str | None) -> None:
    account = apple_account_email or ""
    masked = mask_email(account) if account else "тот же, что в GROMOV"
    messagebox.showinfo(
        "Чтобы приложение открылось",
        "Установка прошла. Открытие на iPhone проверяет лицензию FairPlay.\n\n"
        f"Важно: аккаунт на телефоне должен совпадать с GROMOV ({masked}) "
        "ДО установки. Смена «Медиа и покупки» после установки часто не помогает.\n\n"
        f"1. Настройки → [имя] → Медиаматериалы и покупки → {masked}\n"
        "2. iPhone онлайн (Wi‑Fi / LTE)\n"
        "3. Удалите ярлык со старой установки и поставьте снова уже под этим ID\n"
        "4. Откройте приложение; если спросит пароль Apple ID — введите\n"
        "5. Если снова вылет: в App Store скачайте любое приложение этим ID, затем повторите",
    )
