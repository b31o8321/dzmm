"""Operating-system-backed storage for model provider credentials."""

from __future__ import annotations

from typing import Protocol


class ModelSecretStore(Protocol):
    def get(self, reference: str) -> str | None: ...

    def set(self, reference: str, value: str) -> None: ...

    def delete(self, reference: str) -> None: ...


class KeyringModelSecretStore:
    """Keep model credentials out of SQLite and portable bundles."""

    service = "local.dzmm.model"

    def get(self, reference: str) -> str | None:
        import keyring

        return keyring.get_password(self.service, reference)

    def set(self, reference: str, value: str) -> None:
        import keyring

        keyring.set_password(self.service, reference, value)

    def delete(self, reference: str) -> None:
        import keyring

        try:
            keyring.delete_password(self.service, reference)
        except keyring.errors.PasswordDeleteError:
            pass


def default_model_secret_store() -> ModelSecretStore:
    return KeyringModelSecretStore()
