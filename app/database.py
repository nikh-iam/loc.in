import json
import sqlite3
from contextlib import contextmanager
from .config import DATA, DEFAULTS


class Database:
    def __init__(self, path=None):
        self.path = path or DATA / 'locin.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, name TEXT, ip_address TEXT, last_seen REAL);
                CREATE TABLE IF NOT EXISTS transfers (id TEXT PRIMARY KEY, filename TEXT, device TEXT,
                    direction TEXT, status TEXT, total INTEGER, transferred INTEGER DEFAULT 0,
                    started_at REAL, completed_at REAL, error TEXT);
            ''')
            db.execute("UPDATE transfers SET status='Failed', error='The host restarted.' WHERE status IN ('Waiting','Uploading','Downloading')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def settings(self):
        with self.connect() as db:
            return {**DEFAULTS, **{r['key']: json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}}

    def save(self, values):
        with self.connect() as db:
            db.executemany('INSERT OR REPLACE INTO settings VALUES (?, ?)', [(k, json.dumps(v)) for k, v in values.items()])
