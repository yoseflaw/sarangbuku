import hashlib
import secrets


def digest_invitation_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def generate_invitation_code() -> tuple[str, str]:
    code = secrets.token_urlsafe(32)
    return code, digest_invitation_code(code)
