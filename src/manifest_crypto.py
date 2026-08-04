"""Ed25519 signed-manifest verification for in-app updates (Wave C)."""
from __future__ import annotations

import base64
import json
from pathlib import Path


class ManifestSignatureError(Exception):
    """Manifest signature missing or invalid."""


def _b64decode(value: str) -> bytes:
    text = (value or "").strip()
    if not text:
        raise ManifestSignatureError("Пустая подпись или ключ.")
    pad = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + pad)
    except Exception:
        try:
            return base64.b64decode(text + pad)
        except Exception as exc:
            raise ManifestSignatureError("Некорректный base64 подписи/ключа.") from exc


def canonical_manifest_bytes(payload: dict) -> bytes:
    """Stable bytes used for signing: version + sha256 + setup_url."""
    body = {
        "version": str(payload.get("version") or "").strip(),
        "sha256": str(payload.get("sha256") or payload.get("setup_sha256") or "").strip().lower(),
        "setup_url": str(payload.get("setup_url") or payload.get("download_url") or "").strip(),
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def load_public_key_b64(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-----"):
            continue
        return line
    return text or None


def verify_manifest_ed25519(
    payload: dict,
    *,
    public_key_b64: str,
    signature_b64: str | None = None,
) -> None:
    """Raise ManifestSignatureError if signature does not match."""
    sig = signature_b64 or str(payload.get("signature") or payload.get("sig") or "").strip()
    if not sig:
        raise ManifestSignatureError("В манифесте нет подписи (signature).")
    if not public_key_b64:
        raise ManifestSignatureError("Не задан публичный ключ проверки манифеста.")

    message = canonical_manifest_bytes(payload)
    signature = _b64decode(sig)
    public_raw = _b64decode(public_key_b64)
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise ManifestSignatureError(
            "Для проверки подписи манифеста нужна библиотека cryptography."
        ) from exc

    if len(public_raw) != 32:
        raise ManifestSignatureError("Публичный ключ Ed25519 должен быть 32 байта.")
    if len(signature) != 64:
        raise ManifestSignatureError("Подпись Ed25519 должна быть 64 байта.")

    key = Ed25519PublicKey.from_public_bytes(public_raw)
    try:
        key.verify(signature, message)
    except InvalidSignature as exc:
        raise ManifestSignatureError("Подпись манифеста недействительна.") from exc


def maybe_verify_manifest(
    payload: dict,
    *,
    pubkey_path: Path,
    require: bool = False,
) -> str:
    """Verify when signature+key present. Returns status for logs.

    Backward compatible: unsigned manifests still work until pubkey is shipped
    and/or require=True is set in update.json.
    """
    pubkey = load_public_key_b64(pubkey_path)
    sig = str(payload.get("signature") or payload.get("sig") or "").strip()

    if not pubkey:
        if sig:
            raise ManifestSignatureError(
                "В манифесте есть подпись, но публичный ключ не установлен "
                f"({pubkey_path.name})."
            )
        if require:
            raise ManifestSignatureError("Требуется подпись манифеста, но ключ не найден.")
        return "skip:no-pubkey"

    if not sig:
        if require:
            raise ManifestSignatureError("В манифесте нет Ed25519-подписи.")
        return "skip:no-signature"

    verify_manifest_ed25519(payload, public_key_b64=pubkey, signature_b64=sig)
    return "ok:ed25519"
