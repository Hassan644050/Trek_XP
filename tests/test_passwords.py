import pytest

from app.auth.passwords import hash_password, password_problem, verify_password


def test_correct_password_verifies():
    stored = hash_password("correct horse battery")
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "correct horse battery")


def test_wrong_password_fails():
    assert not verify_password(hash_password("correct horse battery"), "wrong horse battery")


def test_same_password_hashes_differently():
    # Salted: identical passwords must not be recognisable in the database.
    assert hash_password("same password!") != hash_password("same password!")


def test_unknown_user_never_verifies_even_with_the_dummy_password():
    assert not verify_password(None, "trek-xp-timing-equaliser")


def test_corrupt_stored_hash_fails_closed():
    assert not verify_password("not-a-hash", "anything at all")


@pytest.mark.parametrize(
    ("password", "problem"),
    [
        ("short", "at least 10"),
        ("x" * 129, "at most 128"),
        (" leading space ok?", "spaces"),
    ],
)
def test_weak_passwords_are_explained(password, problem):
    assert problem in password_problem(password)


def test_long_passphrase_is_accepted():
    assert password_problem("kaptai lake at sunrise") is None
