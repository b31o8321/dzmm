import keyring

SERVICE = "dzmm"


def store_api_key(ref: str, value: str) -> None:
    keyring.set_password(SERVICE, ref, value)


def get_api_key(ref: str) -> str | None:
    return keyring.get_password(SERVICE, ref)


def delete_api_key(ref: str) -> None:
    try:
        keyring.delete_password(SERVICE, ref)
    except keyring.errors.PasswordDeleteError:
        pass


def mask_key(value: str | None) -> str:
    if not value or len(value) < 10:
        return "***"
    return f"{value[:6]}***{value[-4:]}"
