from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


# argon2id with the library's recommended defaults (RFC 9106 low-memory
# profile). Parameters are encoded in each hash, so raising them later only
# affects new hashes; old ones are upgraded on next sign-in (needs_rehash).
_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 10

# Verified against when the email is unknown, so a missing account takes
# as long to reject as a wrong password and response timing does not reveal
# which emails are registered.
_DUMMY_HASH = _hasher.hash("trek-xp-timing-equaliser")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problem(password: str) -> str | None:
    """Return why a new password is unacceptable, or None if it is fine.

    Length is the rule that matters; composition rules mostly produce
    "Password1!" variants and are deliberately not enforced.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."

    if len(password) > 128:
        return "Password must be at most 128 characters."

    if password.strip() != password:
        return "Password must not start or end with spaces."

    return None
