import tempfile
import time
import unittest
import json
from unittest.mock import patch
from pathlib import Path
from core import Scope, Store, ids


class PrivacyTests(unittest.TestCase):
    def test_scope_retention_and_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            scope = Scope(frozenset({1}), frozenset({2}), frozenset({3}))
            path = Path(directory)/'messages.sqlite3'
            store = Store(path, scope, max_rows=2)
            now = time.time()
            for user, guild, channel, bot in [(9,2,3,False),(1,None,3,False),(1,2,9,False),(1,2,3,True)]:
                self.assertFalse(store.add(10,user,guild,channel,now,'excluded',bot))
            self.assertFalse(store.add(10,1,2,3,now-8*86400,'expired'))
            for mid in (11,12,13):
                self.assertTrue(store.add(mid,1,2,3,now,'allowed'))
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],2)
            store.edit(99,2,3,'not admitted')
            store.delete([12])
            self.assertEqual(store.db.execute('SELECT id FROM messages').fetchall(),[(13,)])
            store.db.close()
            store = Store(path, Scope(frozenset(),frozenset(),frozenset()))
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],0)
            store.db.close()

    def test_snapshot_scope_is_frozen_and_server_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)/'scope.json'
            snapshot.write_text(json.dumps({'users':[1], 'guilds':[2], 'channels':[3]}))
            environment = {'ENUMERATE_CURRENT_SCOPE':'true', 'SCOPE_SNAPSHOT_PATH':str(snapshot),
                           'ALLOWED_GUILD_IDS':'2', 'ALLOWED_USER_IDS':'', 'ALLOWED_CHANNEL_IDS':''}
            with patch.dict('os.environ', environment, clear=True):
                scope = Scope.environment()
                self.assertTrue(scope.allows(1,2,3))
                self.assertFalse(scope.allows(9,2,3))
                self.assertFalse(scope.allows(1,2,9))
            environment['ALLOWED_GUILD_IDS'] = '4'
            with patch.dict('os.environ', environment, clear=True):
                with self.assertRaises(ValueError):
                    Scope.environment()

    def test_fail_closed(self):
        self.assertFalse(Scope(frozenset(),frozenset(),frozenset()).allows(1,2,3))
        with self.assertRaises(ValueError):
            ids('123,no')


if __name__ == '__main__':
    unittest.main()
