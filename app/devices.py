import time
import hashlib


def device_name(agent):
    for marker, name in [('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Android', 'Android'), ('Windows', 'Windows PC'), ('Macintosh', 'Mac'), ('Linux', 'Linux PC')]:
        if marker in agent:
            return name
    return 'Browser'


def touch(db, ip, agent):
    # Identity is intentionally approximate: no network scanning or fingerprinting.
    key = hashlib.sha256((ip + agent[:256]).encode()).hexdigest()[:24]
    with db.connect() as conn:
        conn.execute('INSERT INTO devices VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, ip_address=excluded.ip_address', (key, device_name(agent), ip, time.time()))
    return key


def active(db):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM devices WHERE last_seen > ? ORDER BY last_seen DESC', (time.time() - 60,))]
