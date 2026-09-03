"""Real (non-mocked) round-trip test for scripts/reencrypt_all_keys.py
against a temporary SQLite database — UserApiKey has no PostGIS columns,
so this can run against real SQL instead of a fake session."""
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, UserApiKey, encrypt_key, _fernet_for, SECRET_SALT
from scripts.reencrypt_all_keys import run, _OLD_SECRET_SALT


@pytest.fixture
def sqlite_session_factory():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine, tables=[UserApiKey.__table__])
    SessionFactory = sessionmaker(bind=engine)

    db = SessionFactory()
    # Row 1: encrypted under the CURRENT salt — should be left alone.
    db.add(UserApiKey(user_id=1, username="already_current", openai_api_key=encrypt_key("sk-current-key")))
    # Row 2: encrypted under the LEGACY salt — should be re-encrypted.
    legacy_ciphertext = _fernet_for(_OLD_SECRET_SALT).encrypt(b"sk-legacy-key").decode()
    db.add(UserApiKey(user_id=2, username="legacy", openai_api_key=legacy_ciphertext))
    # Row 3: garbage — neither salt can decrypt it, must be left untouched.
    db.add(UserApiKey(user_id=3, username="corrupt", openai_api_key="not-a-valid-fernet-token"))
    db.commit()
    db.close()

    yield SessionFactory
    os.remove(path)


def test_dry_run_reports_but_does_not_write(sqlite_session_factory):
    stats = run(apply=False, session_factory=sqlite_session_factory)

    assert stats["total"] == 3
    assert stats["already_current"] == 1
    assert stats["reencrypted"] == 1
    assert stats["unreadable"] == [3]

    # Nothing should have changed on disk.
    db = sqlite_session_factory()
    row2 = db.query(UserApiKey).filter(UserApiKey.user_id == 2).first()
    db.close()
    with pytest.raises(Exception):
        _fernet_for(SECRET_SALT).decrypt(row2.openai_api_key.encode())


def test_apply_reencrypts_legacy_row_and_preserves_plaintext(sqlite_session_factory):
    stats = run(apply=True, session_factory=sqlite_session_factory)
    assert stats["reencrypted"] == 1

    db = sqlite_session_factory()
    row1 = db.query(UserApiKey).filter(UserApiKey.user_id == 1).first()
    row2 = db.query(UserApiKey).filter(UserApiKey.user_id == 2).first()
    row3 = db.query(UserApiKey).filter(UserApiKey.user_id == 3).first()
    db.close()

    # Row 2 now decrypts under the CURRENT salt, same plaintext as before.
    assert _fernet_for(SECRET_SALT).decrypt(row2.openai_api_key.encode()).decode() == "sk-legacy-key"
    # Row 1 (already current) untouched in content.
    assert _fernet_for(SECRET_SALT).decrypt(row1.openai_api_key.encode()).decode() == "sk-current-key"
    # Row 3 (unreadable) left byte-for-byte alone.
    assert row3.openai_api_key == "not-a-valid-fernet-token"


def test_running_twice_is_a_no_op_the_second_time(sqlite_session_factory):
    run(apply=True, session_factory=sqlite_session_factory)
    stats = run(apply=True, session_factory=sqlite_session_factory)
    assert stats["already_current"] == 2  # rows 1 and 2 are both current now
    assert stats["reencrypted"] == 0
    assert stats["unreadable"] == [3]
