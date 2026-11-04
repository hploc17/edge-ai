"""Durable idempotency ledger + JPEG files; no image bytes in SQLite.

Only the worker uses this store. Never delete unsent images for quota cleanup.
"""
import json
import os
import sqlite3
import time


class Outbox(object):
    def __init__(self, directory, max_items, max_bytes, jpeg_limit):
        self.directory = directory
        self.max_items, self.max_bytes, self.jpeg_limit = max_items, max_bytes, jpeg_limit
        os.makedirs(directory, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(directory, "ledger.sqlite3"))
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS item (id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                        "state TEXT NOT NULL, size INTEGER NOT NULL DEFAULT 0, result TEXT, "
                        "retry_at REAL NOT NULL DEFAULT 0, updated REAL NOT NULL)")
        self.db.commit()
        for row in self.db.execute("SELECT id FROM item WHERE state='reserved'").fetchall():
            # An interrupted capture cannot safely be repeated for the same command.
            if os.path.isfile(self.path(row[0])):
                self.mark_captured(row[0])
            else:
                partial = self.path(row[0]) + ".part"
                if os.path.isfile(partial):
                    os.unlink(partial)  # Incomplete, never-published write from interrupted process.
                self.finish(row[0], "failed", {"status": "failed", "message": "CAPTURE_INTERRUPTED"})
        # A crash after committing upload success may leave its acknowledged JPEG.
        for row in self.db.execute("SELECT id FROM item WHERE state='complete'").fetchall():
            self.remove_image(row[0])
        self.prune()

    def path(self, key):
        # All identifiers are generated internally (hex hash or UUID).
        if not key or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in key):
            raise ValueError("Unsafe snapshot identifier")
        return os.path.join(self.directory, key + ".jpg")

    def get(self, key):
        row = self.db.execute("SELECT payload,state,result FROM item WHERE id=?", (key,)).fetchone()
        if row:
            return dict(payload=json.loads(row[0]), state=row[1], result=json.loads(row[2]) if row[2] else None)

    def has_capacity(self):
        count, size = self.db.execute("SELECT COUNT(*),COALESCE(SUM(size),0) FROM item "
                                      "WHERE state IN ('reserved','captured')").fetchone()
        return count < self.max_items and size + self.jpeg_limit <= self.max_bytes

    def reserve(self, payload):
        with self.db:
            self.db.execute("INSERT INTO item(id,payload,state,updated) VALUES (?,?,'reserved',?)",
                            (payload["snapshot_id"], json.dumps(payload), time.time()))

    def save(self, key, jpeg, payload):
        path = self.path(key)
        temporary = path + ".part"
        try:
            with open(temporary, "wb") as image:
                image.write(jpeg)
                image.flush()
                os.fsync(image.fileno())
        except OSError:
            if os.path.isfile(temporary):
                os.unlink(temporary)
            raise
        os.replace(temporary, path)
        descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        with self.db:
            self.db.execute("UPDATE item SET payload=? WHERE id=?", (json.dumps(payload), key))
        self.mark_captured(key)

    def mark_captured(self, key):
        with self.db:
            self.db.execute("UPDATE item SET state='captured',size=?,updated=? WHERE id=?",
                            (os.path.getsize(self.path(key)), time.time(), key))

    def finish(self, key, state, result):
        with self.db:
            self.db.execute("UPDATE item SET state=?,result=?,updated=? WHERE id=?",
                            (state, json.dumps(result), time.time(), key))

    def defer(self, key, seconds):
        with self.db:
            self.db.execute("UPDATE item SET retry_at=? WHERE id=?", (time.time() + seconds, key))

    def ready(self):
        row = self.db.execute("SELECT id FROM item WHERE state='captured' AND retry_at<=? "
                              "ORDER BY retry_at,updated LIMIT 1", (time.time(),)).fetchone()
        return row[0] if row else None

    def remove_image(self, key):
        try:
            os.unlink(self.path(key))
        except FileNotFoundError:
            pass

    def prune(self):
        # Keep last 2000 finished receipts; unsent records are never pruned.
        with self.db:
            self.db.execute("DELETE FROM item WHERE id IN (SELECT id FROM item "
                            "WHERE state IN ('complete','failed') ORDER BY updated DESC LIMIT -1 OFFSET 2000)")

    def close(self):
        self.db.close()
