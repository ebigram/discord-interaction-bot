"""Fail-closed scope and minimal, bounded local storage."""
import os
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


def ids(value):
    values = [v.strip() for v in value.split(',') if v.strip()]
    if any(not v.isdecimal() or int(v) <= 0 for v in values):
        raise ValueError('All allowlist entries must be positive numeric Discord IDs')
    return frozenset(int(v) for v in values)


@dataclass(frozen=True)
class Scope:
    users: frozenset
    guilds: frozenset
    channels: frozenset

    def allows(self, user, guild, channel, bot=False):
        return not bot and user in self.users and guild in self.guilds and channel in self.channels

    @classmethod
    def environment(cls):
        scope = cls(*(ids(os.getenv(key, '')) for key in
                     ('ALLOWED_USER_IDS', 'ALLOWED_GUILD_IDS', 'ALLOWED_CHANNEL_IDS')))
        snapshot = os.getenv('SCOPE_SNAPSHOT_PATH', '')
        if snapshot and Path(snapshot).exists() and os.getenv('ENUMERATE_CURRENT_SCOPE', 'false').lower() == 'true':
            data = json.loads(Path(snapshot).read_text())
            saved = cls(*(ids(','.join(map(str, data[key]))) for key in ('users','guilds','channels')))
            if saved.guilds != scope.guilds:
                raise ValueError('Snapshot server differs from configured server')
            return saved
        return scope


class Store:
    def __init__(self, path, scope, days=7, max_rows=10000):
        if not 1 <= days <= 30 or not 1 <= max_rows <= 100000:
            raise ValueError('Retention must be 1-30 days; MAX_MESSAGES must be 1-100000')
        self.scope, self.days, self.max_rows = scope, days, max_rows
        os.umask(0o077)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, user_id INTEGER, guild_id INTEGER, channel_id INTEGER, created_at REAL, content TEXT)')
        self.prune()
        # Scope changes remove previously collected records outside the new scope.
        for row in self.db.execute('SELECT id,user_id,guild_id,channel_id FROM messages').fetchall():
            if not scope.allows(*row[1:]):
                self.db.execute('DELETE FROM messages WHERE id=?', (row[0],))
        self.db.commit()

    def prune(self):
        self.db.execute('DELETE FROM messages WHERE created_at < ?', (time.time()-86400*self.days,))
        self.db.execute('DELETE FROM messages WHERE id IN (SELECT id FROM messages ORDER BY created_at DESC,id DESC LIMIT -1 OFFSET ?)', (self.max_rows,))
        self.db.commit()

    def add(self, mid, user, guild, channel, created, content, bot=False):
        if not self.scope.allows(user, guild, channel, bot) or created < time.time()-86400*self.days:
            return False
        self.db.execute('INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?)', (mid,user,guild,channel,created,content[:4000]))
        self.prune()
        return True

    def edit(self, mid, guild, channel, content):
        # Only modify a record already admitted through the author allowlist.
        self.db.execute('UPDATE messages SET content=? WHERE id=? AND guild_id=? AND channel_id=?', (content[:4000],mid,guild,channel))
        self.db.commit()

    def delete(self, mids):
        self.db.executemany('DELETE FROM messages WHERE id=?', ((mid,) for mid in mids))
        self.db.commit()
