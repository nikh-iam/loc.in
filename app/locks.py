"""Password gates for gateway folders, not filesystem encryption."""
import hashlib
import secrets
import threading
import time
from fastapi import HTTPException
from .config import FOLDER


class FolderLocked(Exception):
    def __init__(self, folder):
        self.folder = folder


class FolderLocks:
    def __init__(self, db):
        self.db = db
        self.guard = threading.RLock()
        self.sessions = {}
        self.attempts = {}
        with db.connect() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS folder_locks (scope TEXT, folder TEXT, salt TEXT, digest TEXT, PRIMARY KEY(scope, folder))')

    def scope(self):
        settings = self.db.settings()
        return settings['storage_mode'] + ':' + (settings['local_folder'] if settings['storage_mode'] == 'local' else settings['folder_id'])

    def records(self):
        with self.db.connect() as connection:
            return {row['folder']: dict(row) for row in connection.execute('SELECT * FROM folder_locks WHERE scope=?', (self.scope(),))}

    def configure(self, folder, password):
        scope = self.scope()
        with self.guard, self.db.connect() as connection:
            if password is None:
                connection.execute('DELETE FROM folder_locks WHERE scope=? AND folder=?', (scope, folder))
            else:
                salt = secrets.token_bytes(16)
                digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
                connection.execute('INSERT OR REPLACE INTO folder_locks VALUES (?,?,?,?)', (scope, folder, salt.hex(), digest))
            self.sessions.clear()

    def unlock(self, folder, password, owner, token):
        now = time.time()
        scope = self.scope()
        with self.guard:
            self.sessions = {key: item for key, item in self.sessions.items() if item['expires'] > now}
            self.attempts = {key: item for key, item in self.attempts.items() if item[1] > now}
            # Limit attempts across all folders for this visitor.
            count, until = self.attempts.get(owner, (0, now + 300))
            if count >= 10:
                raise HTTPException(429, 'Too many password attempts. Try again in five minutes.')
            self.attempts[owner] = (count + 1, until)
            row = self.records().get(folder)
            if not row:
                raise HTTPException(404, 'Protected folder not found.')
            digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(row['salt']), n=16384, r=8, p=1).hex()
            if not secrets.compare_digest(digest, row['digest']):
                raise HTTPException(403, 'Incorrect folder password.')
            session = self.sessions.get(token)
            if not session or session['owner'] != owner:
                token = secrets.token_urlsafe(32)
                session = {'owner': owner, 'grants': set()}
            session['expires'] = now + 1800
            session['grants'].add((scope, folder))
            self.sessions[token] = session
            return token

    def check(self, storage, root, identifier, request, host):
        if host:
            return
        with self.guard:
            records = self.records()
            if not records:
                return
            session = self.sessions.get(request.cookies.get('locin_folders', ''))
            grants = session['grants'] if session and session['owner'] == request.state.device and session['expires'] > time.time() else set()
            scope = self.scope()
            current = identifier
            for _ in range(128):
                metadata = storage.metadata(current)
                current = metadata['id']
                if current in records and (scope, current) not in grants:
                    raise FolderLocked(current)
                if current == root:
                    return
                parents = metadata.get('parents', [])
                if not parents:
                    break
                current = parents[0]
            raise HTTPException(403, 'This item is outside the shared folder.')
