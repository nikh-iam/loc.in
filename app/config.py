"""Small, persistent application settings. Credentials live in the OS vault."""
import os
import re
import sys
from pathlib import Path

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
DATA = Path(os.environ.get('LOCIN_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'loc.in')))
FOLDER = 'application/vnd.google-apps.folder'
CHUNK = 4 * 1024 * 1024
CONTROL_PORT = 4028
DEFAULTS = {'local_name': 'locin', 'folder_id': '', 'folder_name': 'loc.in', 'start_at_login': False,
            'storage_mode': 'drive', 'local_folder': ''}


def valid_id(value):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}', value):
        raise ValueError('Invalid file or folder ID.')
    return value


def valid_name(value):
    value = value.strip()
    if not value or len(value) > 255 or any(ord(c) < 32 or c in '/\\' for c in value) or value in {'.', '..'}:
        raise ValueError('Choose a filename without slashes or control characters (up to 255 characters).')
    return value


def valid_hostname(value):
    value = value.strip().lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', value):
        raise ValueError('Use 1–63 letters, numbers, or hyphens. Start and end with a letter or number.')
    return value
