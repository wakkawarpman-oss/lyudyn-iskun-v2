"""
One-off migration: re-encrypts every UserApiKey.openai_api_key with the
CURRENT SECRET_KEY.

Why this is needed: database/models.py's decrypt_key() soft-falls-back to the
legacy hardcoded salt (_OLD_SECRET_SALT) for keys encrypted before SECRET_KEY
became mandatory, so reads never break — but a key that's only ever READ
(never re-saved through the bot's /key flow) stays encrypted under the legacy
salt indefinitely. This script closes that gap by decrypting and re-saving
every row once, so everything ends up under the current SECRET_KEY.

Deliberately does NOT use decrypt_key()'s full fallback chain: decrypt_key
also tries a bare base64 decode and, failing that, returns the ciphertext
unchanged — re-encrypting either of those results would silently corrupt an
unreadable row instead of leaving it alone for manual review. This script
only accepts a genuine Fernet decrypt (current or legacy salt) as "readable".

Usage:
    python -m scripts.reencrypt_all_keys           # dry run, writes nothing
    python -m scripts.reencrypt_all_keys --apply    # actually re-encrypts and commits
"""
import argparse

from database.models import (
    SessionLocal,
    UserApiKey,
    encrypt_key,
    _fernet_for,
    SECRET_SALT,
    _OLD_SECRET_SALT,
)


def _try_decrypt(stored_key: str):
    """Returns (plaintext, salt_label) on success, or None if neither the
    current nor the legacy salt can decrypt it via Fernet."""
    if not stored_key:
        return None
    for salt, label in ((SECRET_SALT, "current"), (_OLD_SECRET_SALT, "legacy")):
        try:
            return _fernet_for(salt).decrypt(stored_key.encode()).decode(), label
        except Exception:
            continue
    return None


def run(apply: bool, session_factory=SessionLocal) -> dict:
    db = session_factory()
    already_current = 0
    reencrypted = 0
    unreadable = []
    try:
        rows = db.query(UserApiKey).all()
        for row in rows:
            result = _try_decrypt(row.openai_api_key)
            if result is None:
                unreadable.append(row.user_id)
                continue
            plaintext, salt_used = result
            if salt_used == "current":
                already_current += 1
                continue
            if apply:
                row.openai_api_key = encrypt_key(plaintext)
            reencrypted += 1
        if apply:
            db.commit()
        total = len(rows)
    finally:
        db.close()

    return {
        "total": total,
        "already_current": already_current,
        "reencrypted": reencrypted,
        "unreadable": unreadable,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write re-encrypted keys and commit (default: dry run, no writes)",
    )
    args = parser.parse_args()

    stats = run(apply=args.apply)

    print(f"Total rows: {stats['total']}")
    print(f"Already on current salt: {stats['already_current']}")
    print(f"{'Re-encrypted' if args.apply else 'Would re-encrypt'}: {stats['reencrypted']}")
    if stats["unreadable"]:
        print(
            f"UNREADABLE (neither current nor legacy salt worked, left "
            f"untouched — needs manual review): {stats['unreadable']}"
        )
    if not args.apply:
        print("\nDry run only — pass --apply to write changes.")


if __name__ == "__main__":
    main()
