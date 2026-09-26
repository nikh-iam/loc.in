import threading
import time
import uuid
from fastapi import HTTPException


class Transfers:
    def __init__(self, db):
        self.db = db
        self.lock = threading.RLock()
        self.uploads = {}
        self.downloads = set()
        self.limit = 3

    def begin(self, filename, device, direction, total):
        with self.lock:
            if len(self.uploads) + len(self.downloads) >= self.limit:
                raise HTTPException(429, 'Three transfers are already active. Please try again shortly.')
            key = uuid.uuid4().hex
            with self.db.connect() as db:
                db.execute('INSERT INTO transfers (id, filename, device, direction, status, total, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (key, filename, device, direction, 'Uploading' if direction == 'upload' else 'Downloading', total, time.time()))
            if direction == 'download':
                self.downloads.add(key)
            return key

    def progress(self, key, count):
        with self.db.connect() as db:
            db.execute('UPDATE transfers SET transferred=? WHERE id=?', (count, key))

    def finish(self, key, status='Completed', error=None):
        with self.lock:
            self.uploads.pop(key, None)
            self.downloads.discard(key)
            with self.db.connect() as db:
                db.execute("UPDATE transfers SET status=?, completed_at=?, error=? WHERE id=? AND status IN ('Waiting','Uploading','Downloading')", (status, time.time(), error, key))

    def list(self, device=None):
        with self.db.connect() as db:
            if device is None:
                rows = db.execute('SELECT * FROM transfers ORDER BY started_at DESC LIMIT 100')
            else:
                rows = db.execute('SELECT * FROM transfers WHERE device=? ORDER BY started_at DESC LIMIT 100', (device,))
            return [dict(r) for r in rows]

    def reap(self):
        with self.lock:
            for key, item in list(self.uploads.items()):
                if time.time() - item['touched'] > 600 and not item['lock'].locked():
                    self.finish(key, 'Failed', 'Upload timed out. Please try again.')

    def stop(self):
        with self.lock:
            for key in list(self.uploads):
                self.finish(key, 'Cancelled', 'Service stopped.')
