from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "002_security_enforce.sql"


def test_security_enforcement_migration_requires_hashes_and_removes_plaintext_pin():
    assert MIGRATION.is_file()
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "pin_hash is null" in sql
    assert "revoke all privileges" in sql
    assert "from anon, authenticated" in sql
    assert "drop column if exists pin" in sql
    assert "alter column pin_hash set not null" in sql

