from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet


class SecretBox:
    def __init__(self, key_path: Path, raw_key: str | None = None) -> None:
        self._key_path = key_path
        self._key = self._load_or_create_key(raw_key)
        self._fernet = Fernet(self._key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")

    @property
    def key_material(self) -> bytes:
        return self._key

    def _load_or_create_key(self, raw_key: str | None) -> bytes:
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_key:
            return raw_key.encode("utf-8")
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        return key
