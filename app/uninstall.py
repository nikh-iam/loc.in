"""Remove only loc.in-owned per-user state; never traverse shared storage."""
import os
import shutil
import sqlite3
import json
from contextlib import closing
from pathlib import Path
import keyring
from .local import check_path
from .startup import set_startup


def cleanup_user_data(local_appdata=None, vault=None, disable_startup=None):
    base = Path(local_appdata or os.environ['LOCALAPPDATA']).absolute()
    root = base / 'loc.in'
    vault = vault or keyring
    disable_startup = disable_startup or (lambda: set_startup(False))
    # Refuse redirected application directories before touching their contents.
    if root.exists():
        check_path(root)
        if root.resolve().parent != base.resolve():
            raise ValueError('Application data location is not safe to clean.')
        cache = root / 'webview'
        shared = None
        database = root / 'locin.db'
        if database.exists():
            check_path(database)
            try:
                with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
                    row = connection.execute("SELECT value FROM settings WHERE key='local_folder'").fetchone()
                    if row and json.loads(row[0]):
                        shared = Path(json.loads(row[0])).resolve()
            except (sqlite3.Error, ValueError):
                pass
        cache_is_shared = shared is not None and (shared == cache.resolve() or shared in cache.resolve().parents or cache.resolve() in shared.parents)
        if cache.exists() and not cache_is_shared:
            check_path(cache)
            for directory, folders, files in os.walk(cache, followlinks=False):
                for name in folders + files:
                    check_path(Path(directory) / name)
            # Resolved target is inside the fixed app-owned directory.
            if cache.resolve().parent != root.resolve():
                raise ValueError('Application cache location is not safe to clean.')
            shutil.rmtree(cache)
        for name in ('locin.db', 'locin.db-wal', 'locin.db-shm', 'locin.db-journal', 'smoke.log'):
            path = root / name
            if path.exists():
                check_path(path)
                path.unlink()
        # Unknown files may belong to the user. Never delete them recursively.
        if not any(root.iterdir()):
            root.rmdir()
    for account in ('google-oauth', 'google-client'):
        try:
            vault.delete_password('loc.in', account)
        except keyring.errors.PasswordDeleteError:
            pass
    disable_startup()
