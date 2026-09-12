import pytest

from scripts.migrate_pin_hashes import migrate_pin_hashes


class FakeQuery:
    def __init__(self, client, operation):
        self.client = client
        self.operation = operation

    def execute(self):
        if self.operation == "select":
            return type("Response", (), {"data": self.client.players})()
        self.client.updated += 1
        return type("Response", (), {"data": []})()

    def select(self, _columns):
        return self

    def update(self, values):
        self.operation = "update"
        self.client.values.append(values)
        return self

    def eq(self, _column, _value):
        return self


class FakeClient:
    def __init__(self, players):
        self.players = players
        self.updated = 0
        self.values = []

    def table(self, _name):
        return FakeQuery(self, "select")


def test_migration_aborts_before_updating_when_a_player_has_no_pin():
    client = FakeClient([{"id": 1, "pin": None}])

    with pytest.raises(RuntimeError, match="sin PIN"):
        migrate_pin_hashes(client)

    assert client.updated == 0


def test_migration_writes_one_scrypt_hash_for_each_player():
    client = FakeClient([{"id": 1, "pin": "1234"}, {"id": 2, "pin": "5678"}])

    assert migrate_pin_hashes(client) == 2
    assert client.updated == 2
    assert all(value["pin_hash"].startswith("scrypt$") for value in client.values)
