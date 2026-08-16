from __future__ import annotations

from database.db import COLLECTOR_SOURCE, SpendingDatabase


class Checkpoint:
    def __init__(self, db: SpendingDatabase, source: str = COLLECTOR_SOURCE):
        self.db = db
        self.source = source

    def last_message_id(self) -> int:
        return self.db.get_checkpoint(self.source)

    def update(self, message_id: int) -> None:
        current = self.last_message_id()
        if message_id > current:
            self.db.set_checkpoint(message_id, self.source)

    def reset(self) -> None:
        self.db.set_checkpoint(0, self.source)
