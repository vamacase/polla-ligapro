from datetime import datetime, timezone

from services.notification_worker import process_notifications, retry_at


def test_retry_wait_grows_and_is_bounded():
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)

    assert retry_at(now, 1) > now
    assert retry_at(now, 6) <= now.replace(hour=23, minute=59)


class FakeExecution:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class FakeUpdate:
    def __init__(self, updates, notification_id):
        self._updates = updates
        self._notification_id = notification_id

    def execute(self):
        self._updates.append((self._notification_id, self._data))
        return FakeExecution([])

    def eq(self, _column, notification_id):
        self._notification_id = notification_id
        return self

    def update(self, data):
        self._data = data
        return self


class FakeTable:
    def __init__(self, updates):
        self._updates = updates

    def update(self, data):
        updater = FakeUpdate(self._updates, None)
        return updater.update(data)


class FakeDb:
    def __init__(self, claimed):
        self.claimed = claimed
        self.updates = []

    def rpc(self, _name, _args):
        return FakeExecution(self.claimed)

    def table(self, _name):
        return FakeTable(self.updates)


def test_worker_marks_accepted_delivery_as_sent():
    db = FakeDb([{"id": 7, "intentos": 1, "destinatario": "ana@example.test",
                  "payload": {"subject": "Asunto", "html": "<p>Hola</p>"}}])

    result = process_notifications(db, lambda recipient, subject, html: True)

    assert result == {"claimed": 1, "sent": 1, "retrying": 0, "failed": 0}
    assert db.updates[0][0] == 7
    assert db.updates[0][1]["estado"] == "enviado"


def test_worker_requeues_failed_delivery():
    db = FakeDb([{"id": 8, "intentos": 1, "destinatario": "ana@example.test",
                  "payload": {"subject": "Asunto", "html": "<p>Hola</p>"}}])

    result = process_notifications(db, lambda recipient, subject, html: False)

    assert result == {"claimed": 1, "sent": 0, "retrying": 1, "failed": 0}
    assert db.updates[0][1]["estado"] == "pendiente"
    assert db.updates[0][1]["ultimo_error"] == "SMTP no aceptó el mensaje"
