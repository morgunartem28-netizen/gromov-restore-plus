from __future__ import annotations

import shutil
from pathlib import Path

# Запас под крупные IPA (Авито ~800 МБ) + временные файлы при установке.
_MIN_FREE_BYTES = 2 * 1024**3


class DiskSpaceError(RuntimeError):
    pass


def ensure_download_space(target_dir: Path, required_bytes: int = _MIN_FREE_BYTES) -> None:
    usage = shutil.disk_usage(target_dir)
    if usage.free < required_bytes:
        free_gb = usage.free / (1024**3)
        raise DiskSpaceError(
            f"Недостаточно места на диске ({free_gb:.1f} ГБ свободно).\n"
            "Освободите место и попробуйте снова."
        )
