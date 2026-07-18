from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app_paths import data_dir, install_dir, tools_dir
from ipa_utils import cleanup_download_artifacts, is_valid_ipa, read_ipa_bundle_id
from security_utils import protect_sensitive_file, protect_sensitive_tree, redact_secrets
from subprocess_utils import popen_hidden, run_hidden


class IpatoolError(RuntimeError):
    pass


class IpatoolTwoFactorRequired(IpatoolError):
    pass


@dataclass
class SearchResult:
    app_id: int
    bundle_id: str
    name: str
    version: str = ""


class IpatoolClient:
    def __init__(self, ipatool_path: str | None = None, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or install_dir()
        self.data_root = data_dir() if base_dir is None else self.base_dir / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.ipatool_path = ipatool_path or self._resolve_ipatool()
        self.log_path = self.data_root / "ipatool.log"
        self.keychain_pass_path = self.data_root / "keychain.pass"
        if self.keychain_pass_path.exists():
            protect_sensitive_file(self.keychain_pass_path)
        self._scrub_legacy_secret_logs()

    @staticmethod
    def _ipatool_home() -> Path:
        return Path.home() / ".ipatool"

    def _scrub_legacy_secret_logs(self) -> None:
        """Drop historical logs that may contain plaintext --password values."""
        try:
            if not self.log_path.exists():
                return
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"(?i)--password\s+(?!\*\*\*)\S+", text):
                self.log_path.write_text(
                    "[log cleared: previous entries may have contained secrets]\n",
                    encoding="utf-8",
                )
                protect_sensitive_file(self.log_path)
        except OSError:
            pass

    def _resolve_ipatool(self) -> str:
        from_env = os.environ.get("IPATOOL_PATH")
        if from_env and Path(from_env).exists():
            return from_env

        found = shutil.which("ipatool")
        if found:
            return found

        local = tools_dir() / "ipatool.exe"
        if local.exists():
            return str(local)

        raise IpatoolError(
            "ipatool не найден. Скачайте ipatool для Windows с "
            "https://github.com/majd/ipatool/releases и положите в tools/ipatool.exe "
            "или добавьте в PATH."
        )

    def _keychain_passphrase(self) -> str:
        if self.keychain_pass_path.exists():
            passphrase = self.keychain_pass_path.read_text(encoding="utf-8").strip()
            if passphrase:
                protect_sensitive_file(self.keychain_pass_path)
                return passphrase
        passphrase = secrets.token_urlsafe(24)
        self.keychain_pass_path.write_text(passphrase, encoding="utf-8")
        protect_sensitive_file(self.keychain_pass_path)
        return passphrase

    def clear_local_session_secrets(self) -> None:
        """Remove local passphrase and ipatool session cookies after logout."""
        try:
            if self.keychain_pass_path.exists():
                self.keychain_pass_path.unlink()
        except OSError:
            pass

        ipatool_home = self._ipatool_home()
        cookies = ipatool_home / "cookies"
        try:
            if cookies.exists():
                cookies.unlink()
        except OSError:
            pass
        protect_sensitive_tree(ipatool_home)

    def harden_session_store(self) -> None:
        """Best-effort ACL lockdown for ~/.ipatool after login."""
        protect_sensitive_tree(self._ipatool_home())
        if self.keychain_pass_path.exists():
            protect_sensitive_file(self.keychain_pass_path)

    def _log_run(self, args: list[str], completed: subprocess.CompletedProcess[str]) -> None:
        safe_args = []
        skip_next = False
        for arg in args:
            if skip_next:
                safe_args.append("***")
                skip_next = False
                continue
            if arg in ("--password", "--auth-code", "--keychain-passphrase"):
                safe_args.append(arg)
                skip_next = True
                continue
            safe_args.append(arg)

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n[{stamp}] {' '.join(safe_args)}\n"
            f"exit={completed.returncode}\n"
            f"stdout={redact_secrets(completed.stdout or '')}\n"
            f"stderr={redact_secrets(completed.stderr or '')}\n"
        )
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)

    def _run(self, args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        command = [
            self.ipatool_path,
            *args,
            "--format",
            "json",
            "--keychain-passphrase",
            self._keychain_passphrase(),
            "--non-interactive",
        ]
        try:
            completed = run_hidden(
                command,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError as exc:
            raise IpatoolError(f"Не удалось запустить ipatool: {self.ipatool_path}") from exc

        self._log_run(args, completed)
        return completed

    def _parse_json(self, completed: subprocess.CompletedProcess[str]) -> dict:
        stdout = (completed.stdout or "").strip()
        if not stdout:
            raise IpatoolError(self.format_error(self._extract_error(completed)))
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise IpatoolError(f"Некорректный JSON от ipatool:\n{stdout}\n{completed.stderr}") from exc

    def _extract_error(self, completed: subprocess.CompletedProcess[str]) -> str:
        raw = (completed.stdout or completed.stderr or "").strip()
        if not raw:
            return "Пустой ответ ipatool"
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("error"):
                return str(payload["error"])
        except json.JSONDecodeError:
            pass
        return raw

    def auth_info(self) -> dict:
        completed = self._run(["auth", "info"])
        if completed.returncode != 0:
            raise IpatoolError(self.format_error(self._extract_error(completed)))
        return self._parse_json(completed)

    def auth_logout(self) -> None:
        completed = self._run(["auth", "revoke"])
        self.clear_local_session_secrets()
        if completed.returncode != 0:
            raise IpatoolError(self.format_error(self._extract_error(completed)))

    def auth_login(self, email: str, password: str, auth_code: str | None = None) -> dict:
        code = (auth_code or "").replace(" ", "").strip()
        args = ["auth", "login", "--email", email, "--password", password]
        if code:
            args.extend(["--auth-code", code])

        completed = self._run(args)
        combined = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()

        if completed.returncode == 0:
            if self.needs_two_factor(combined) and not code:
                raise IpatoolTwoFactorRequired(
                    "Код подтверждения отправлен на iPhone или Mac. Введите 6 цифр и нажмите «Войти» снова."
                )
            self.harden_session_store()
            if completed.stdout and completed.stdout.strip():
                try:
                    payload = json.loads(completed.stdout)
                    if payload.get("success") is True or payload.get("email"):
                        return payload
                except json.JSONDecodeError:
                    pass
            return self.auth_info()

        error_text = self._extract_error(completed)
        if self.needs_two_factor(error_text) and not code:
            raise IpatoolTwoFactorRequired(
                "Код подтверждения отправлен на iPhone или Mac. Введите 6 цифр и нажмите «Войти» снова."
            )
        raise IpatoolError(self.format_error(error_text))

    @staticmethod
    def format_error(error_text: str) -> str:
        text = error_text.strip()
        if not text:
            return "Неизвестная ошибка авторизации."

        lower = text.lower()
        if "keychain passphrase is required" in lower or "failed to save account in keychain" in lower:
            return (
                "Не удалось сохранить сессию Apple ID на этом ПК.\n"
                "Закройте приложение, удалите папку C:\\Users\\ВАШ_ПОЛЬЗОВАТЕЛЬ\\.ipatool "
                "и войдите снова."
            )
        if "unexpected hex digit" in lower or "failed to unmarshal xml" in lower:
            return (
                "Apple вернул некорректный ответ при входе.\n"
                "Перезапустите приложение и попробуйте снова через 1–2 минуты."
            )
        if "something went wrong" in lower and "auth code" not in lower:
            return (
                "Apple не принял вход.\n"
                "Если вводили код 2FA — запросите новый код и введите его сразу (код живёт ~30 сек).\n"
                "Проверьте также email и пароль."
            )
        if "account is disabled" in lower:
            return "Неверный email или пароль Apple ID."
        if "browser sign-in" in lower:
            return (
                "Apple требует подтверждение в браузере.\n"
                "Откройте https://appleid.apple.com, войдите в аккаунт, затем повторите попытку."
            )
        if "rate limit" in lower or "429" in lower:
            return "Apple временно ограничил попытки входа. Подождите 5–10 минут."
        if "password is required" in lower:
            return "Введите пароль Apple ID."
        if "app not found" in lower:
            return (
                "Приложение не найдено в каталоге App Store.\n"
                "Для удалённых приложений скачивание идёт только по App Store ID.\n"
                "Попробуйте снова — если ошибка повторится, проверьте ID в настройках приложения."
            )
        if "license" in lower and "required" in lower:
            return (
                "У вашего Apple ID нет лицензии на это приложение.\n"
                "Оно должно было быть раньше скачано именно с этого аккаунта."
            )
        if "failed to open zip reader" in lower or "not a valid zip" in lower:
            return (
                "Скачивание прервалось — файл IPA повреждён или не докачался.\n"
                "Временные файлы будут удалены. Нажмите «Скачать и установить» ещё раз.\n"
                "Авито весит ~800 МБ — не закрывайте программу 5–10 минут."
            )
        if "badlogin" in lower or "incorrect" in lower:
            return "Неверный пароль или код подтверждения."
        return text

    @staticmethod
    def needs_two_factor(error_text: str) -> bool:
        text = error_text.lower()
        markers = (
            "verification",
            "2fa",
            "auth-code",
            "auth code",
            "two-factor",
            "two factor",
            "security code",
            "incorrect login",
            "-22406",
            "-22421",
            "mzfinance.badlogin",
            "2fa code is required",
            "auth code is required",
            "badlogin",
        )
        return any(marker in text for marker in markers)

    def search(self, term: str, limit: int = 10) -> list[SearchResult]:
        completed = self._run(["search", term, "--limit", str(limit)])
        if completed.returncode != 0:
            raise IpatoolError(self.format_error(self._extract_error(completed)))
        payload = self._parse_json(completed)
        apps = payload.get("apps") or payload.get("results") or []
        results: list[SearchResult] = []
        for item in apps:
            results.append(
                SearchResult(
                    app_id=int(item.get("id") or item.get("trackId") or 0),
                    bundle_id=str(item.get("bundleID") or item.get("bundleId") or ""),
                    name=str(item.get("name") or item.get("trackName") or ""),
                    version=str(item.get("version") or ""),
                )
            )
        return [item for item in results if item.app_id and item.bundle_id]

    def download(
        self,
        *,
        app_id: int,
        bundle_id: str,
        output_dir: Path,
        purchase: bool = True,
        use_lookup: bool = False,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        cleanup_download_artifacts(output_dir, app_id)
        args = [
            "download",
            "--app-id",
            str(app_id),
            "--output",
            str(output_dir),
        ]
        # Для удалённых из App Store приложений lookup по bundle ID всегда падает.
        if use_lookup and bundle_id:
            args.extend(["--bundle-identifier", bundle_id])
        if purchase:
            args.append("--purchase")

        completed = self._run(args)
        if completed.returncode != 0:
            raise IpatoolError(self.format_error(self._extract_error(completed)))

        payload = self._parse_json(completed)
        downloaded = payload.get("path") or payload.get("output") or payload.get("file")
        path: Path | None = None
        if downloaded:
            candidate = Path(downloaded)
            try:
                resolved = candidate.resolve()
                output_resolved = output_dir.resolve()
                if resolved.is_file() and resolved.parent == output_resolved:
                    path = resolved
            except OSError:
                path = None
        if path is None:
            patterns = (f"{app_id}_*.ipa", f"*_{app_id}_*.ipa")
            candidates: list[Path] = []
            for pattern in patterns:
                candidates.extend(output_dir.glob(pattern))
            candidates = sorted(
                {item.resolve() for item in candidates if item.is_file()},
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                raise IpatoolError("IPA скачан, но путь к файлу не найден.")
            path = candidates[0]

        if not is_valid_ipa(path, expected_bundle_id=bundle_id or None):
            actual_bundle = read_ipa_bundle_id(path)
            try:
                path.unlink()
            except OSError:
                pass
            cleanup_download_artifacts(output_dir, app_id)
            if actual_bundle and bundle_id:
                raise IpatoolError(
                    f"Скачан не тот IPA: ожидался {bundle_id}, получен {actual_bundle}.\n"
                    "Проверьте App Store ID в каталоге."
                )
            raise IpatoolError(
                "Скачанный файл повреждён или не докачался.\n"
                "Попробуйте установить приложение ещё раз."
            )
        return path
