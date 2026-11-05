"""Account authentication for the public OpenYuGi service."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from src.core.config import ConfigManager, config_manager


AUTH_SESSION_KEY = "authenticated"
AUTH_REVISION_KEY = "auth_revision"
AUTH_USER_KEY = "auth_user"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_USERNAME_LENGTH = 64
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,31}")
STORAGE_SECRET_PATH = Path("data/.storage_secret")
_ACCOUNTS_LOCK = threading.Lock()


class AuthService:
    """The first account lives in config. Everyone else is a free account."""

    def __init__(self, manager: ConfigManager = config_manager, accounts_file: Path | None = None) -> None:
        self.config_manager = manager
        if accounts_file is None:
            accounts_file = Path(manager.config_file).with_name("accounts.json")
        self.accounts_file = Path(accounts_file)

    @staticmethod
    def validate_username(username: str) -> str:
        normalized = username.strip() if isinstance(username, str) else ""
        if not normalized:
            raise ValueError("Username is required.")
        if len(normalized) > MAX_USERNAME_LENGTH:
            raise ValueError(f"Username must be {MAX_USERNAME_LENGTH} characters or fewer.")
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ValueError("Username cannot contain control characters.")
        return normalized

    @staticmethod
    def validate_password(password: str) -> None:
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise ValueError(f"Password must be {MAX_PASSWORD_LENGTH} characters or fewer.")

    def authenticate(self, username: str, password: str) -> bool:
        return self.identify(username, password) is not None

    def identify(self, username: str, password: str) -> str | None:
        """Return the stored username when the password matches, otherwise None."""
        raw = username.strip() if isinstance(username, str) else ""
        secret = password if isinstance(password, str) else ""
        primary = self.config_manager.get_auth_username()
        primary_hash = self.config_manager.get_auth_password_hash()
        if raw.casefold() == primary.casefold() and self._password_matches(primary_hash, secret):
            # Keep the exact configured spelling. Tests compare that string.
            if hmac.compare_digest(raw.encode("utf-8"), primary.encode("utf-8")) or raw.casefold() == primary.casefold():
                return primary
        for account in self._read_accounts():
            if raw.casefold() == str(account.get("username", "")).casefold() and self._password_matches(
                str(account.get("password_hash", "")), secret
            ):
                return str(account["username"])
        return None

    @staticmethod
    def _password_matches(password_hash: str, password: str) -> bool:
        try:
            return bool(password_hash) and check_password_hash(password_hash, password)
        except (TypeError, ValueError):
            return False

    def register(self, username: str, password: str, confirm_password: str) -> str:
        """Create a free account. The username is the public handle and the data folder."""
        if password != confirm_password:
            raise ValueError("Las contraseñas no coinciden.")
        handle = self._public_username(username)
        self.validate_password(password)
        primary = self.config_manager.get_auth_username()
        if handle.casefold() == primary.casefold():
            raise ValueError("Ese usuario ya existe.")
        with _ACCOUNTS_LOCK:
            accounts = self._read_accounts()
            if any(str(account.get("username", "")).casefold() == handle.casefold() for account in accounts):
                raise ValueError("Ese usuario ya existe.")
            accounts.append({
                "username": handle,
                "password_hash": generate_password_hash(password, method="scrypt"),
            })
            self._write_accounts(accounts)
        user_root = Path("data") / "users" / handle
        (user_root / "collections").mkdir(parents=True, exist_ok=True)
        (user_root / "decks").mkdir(parents=True, exist_ok=True)
        return handle

    def _public_username(self, username: str) -> str:
        normalized = self.validate_username(username)
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError("Usa de 3 a 32 letras, números, guiones o guiones bajos.")
        return normalized

    def _read_accounts(self) -> list[dict]:
        if not self.accounts_file.exists():
            return []
        try:
            data = json.loads(self.accounts_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        return [account for account in data if isinstance(account, dict)]

    def _write_accounts(self, accounts: list[dict]) -> None:
        self.accounts_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.accounts_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
        try:
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(temporary, self.accounts_file)

    def update_credentials(
        self,
        current_password: str,
        new_username: str,
        new_password: str = "",
        confirm_password: str = "",
    ) -> None:
        if not self.authenticate(self.config_manager.get_auth_username(), current_password):
            raise ValueError("Current password is incorrect.")

        username = self.validate_username(new_username)
        password_hash = self.config_manager.get_auth_password_hash()
        if new_password or confirm_password:
            if new_password != confirm_password:
                raise ValueError("New passwords do not match.")
            self.validate_password(new_password)
            password_hash = generate_password_hash(new_password, method="scrypt")

        self.config_manager.set_auth_credentials(username, password_hash)

    def update_account(
        self,
        actor: str,
        current_password: str,
        new_username: str,
        new_password: str = "",
        confirm_password: str = "",
    ) -> str:
        """Update the signed-in account and return its stored username."""
        canonical = self.identify(actor, current_password)
        if canonical is None:
            raise ValueError("Current password is incorrect.")
        primary = self.config_manager.get_auth_username()
        if canonical.casefold() == primary.casefold():
            self.update_credentials(current_password, new_username, new_password, confirm_password)
            return self.config_manager.get_auth_username()

        if new_password or confirm_password:
            if new_password != confirm_password:
                raise ValueError("New passwords do not match.")
            self.validate_password(new_password)
        handle = self._public_username(new_username)
        with _ACCOUNTS_LOCK:
            accounts = self._read_accounts()
            current = next(
                (account for account in accounts if str(account.get("username", "")).casefold() == canonical.casefold()),
                None,
            )
            if current is None:
                raise ValueError("Current password is incorrect.")
            if handle.casefold() != canonical.casefold() and (
                handle.casefold() == primary.casefold()
                or any(str(account.get("username", "")).casefold() == handle.casefold() for account in accounts)
            ):
                raise ValueError("Ese usuario ya existe.")
            if new_password:
                current["password_hash"] = generate_password_hash(new_password, method="scrypt")
            if handle != canonical:
                old_root = Path("data") / "users" / canonical
                new_root = Path("data") / "users" / handle
                if old_root.exists() and not new_root.exists():
                    old_root.rename(new_root)
                current["username"] = handle
            self._write_accounts(accounts)
        return handle

    def revision(self) -> str:
        """Identify the primary account so changes invalidate its older sessions."""
        return self.revision_for(self.config_manager.get_auth_username())

    def revision_for(self, username: str) -> str:
        """Identify one account. A password change signs that account out."""
        canonical = username.strip() if isinstance(username, str) else ""
        primary = self.config_manager.get_auth_username()
        if canonical.casefold() == primary.casefold():
            password_hash = self.config_manager.get_auth_password_hash()
            canonical = primary
        else:
            password_hash = ""
            for account in self._read_accounts():
                if str(account.get("username", "")).casefold() == canonical.casefold():
                    canonical = str(account["username"])
                    password_hash = str(account.get("password_hash", ""))
                    break
        payload = f"{canonical}\0{password_hash}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_storage_secret(
    secret_path: Path = STORAGE_SECRET_PATH,
    environ: dict[str, str] | None = None,
) -> str:
    """Load a stable session signing secret, generating a local one if needed."""
    environment = os.environ if environ is None else environ
    configured_secret = environment.get("OPENYUGI_STORAGE_SECRET", "")
    if configured_secret:
        if len(configured_secret) < 32:
            raise ValueError("OPENYUGI_STORAGE_SECRET must be at least 32 characters.")
        return configured_secret

    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        secret = secret_path.read_text(encoding="utf-8").strip()
        if len(secret) < 32:
            raise ValueError(f"Session secret in {secret_path} is invalid.")
        try:
            os.chmod(secret_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return secret
    except OSError as error:
        raise RuntimeError(
            f"Unable to create session secret at {secret_path}. "
            "Set OPENYUGI_STORAGE_SECRET or make its parent directory writable."
        ) from error

    secret = secrets.token_urlsafe(48)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(secret)
    return secret


# SECURITY: Passwords use Werkzeug's memory-hard, salted scrypt hashes. The hash
# and session signing secret still live in local files. Deployments should use
# HTTPS, restrict those files to the service account, and inject a strong
# OPENYUGI_STORAGE_SECRET via the environment (or a secrets manager).
auth_service = AuthService()
