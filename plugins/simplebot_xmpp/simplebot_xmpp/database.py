# -*- coding: utf-8 -*-
import sqlite3


class DBManager:
    def __init__(self, db_path):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute(
                '''CREATE TABLE IF NOT EXISTS channels
                (id TEXT PRIMARY KEY)''')
            self.db.execute(
                '''CREATE TABLE IF NOT EXISTS cchats
                (id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL)''')
            self.db.execute(
                '''CREATE TABLE IF NOT EXISTS nicks
                (addr TEXT PRIMARY KEY,
                nick TEXT NOT NULL)''')
            self.db.execute(
                '''CREATE TABLE IF NOT EXISTS whitelist
                (channel TEXT PRIMARY KEY)''')

    def execute(self, statement, args=()):
        return self.db.execute(statement, args)

    def commit(self, statement, args=()):
        with self.db:
            return self.db.execute(statement, args)

    def close(self):
        self.db.close()

    ###### channels ########

    def channel_exists(self, jid):
        jid = jid.lower()
        r = self.execute(
            'SELECT * FROM channels WHERE id=?', (jid,)).fetchone()
        return r is not None

    def get_channel_by_gid(self, gid):
        r = self.db.execute(
            'SELECT channel from cchats WHERE id=?', (gid,)).fetchone()
        return r and r[0]

    def get_channels(self):
        for r in self.db.execute('SELECT id FROM channels'):
            yield r[0]

    def add_channel(self, jid):
        self.commit('INSERT INTO channels VALUES (?)', (jid.lower(),))

    def remove_channel(self, jid):
        self.commit('DELETE FROM channels WHERE id=?', (jid.lower(),))

    ###### cchats ########

    def get_cchats(self, channel):
        for r in self.db.execute('SELECT id FROM cchats WHERE channel=?',
                                 (channel.lower(),)).fetchall():
            yield r[0]

    def add_cchat(self, gid, channel):
        self.commit('INSERT INTO cchats VALUES (?,?)', (gid, channel))

    def remove_cchat(self, gid):
        self.commit('DELETE FROM cchats WHERE id=?', (gid,))

    ###### nicks ########

    def get_nick(self, addr):
        r = self.execute(
            'SELECT nick from nicks WHERE addr=?', (addr,)).fetchone()
        if r:
            return r[0]
        else:
            i = 1
            while True:
                nick = 'User{}'.format(i)
                if not self.get_addr(nick):
                    self.set_nick(addr, nick)
                    break
                i += 1
            return nick

    def set_nick(self, addr, nick):
        self.commit('REPLACE INTO nicks VALUES (?,?)', (addr, nick))

    def get_addr(self, nick):
        r = self.execute(
            'SELECT addr FROM nicks WHERE nick=?', (nick,)).fetchone()
        return r and r[0]

    ###### whitelist ########

    def is_whitelisted(self, jid):
        rows = self.execute('SELECT channel FROM whitelist').fetchall()
        if not rows:
            return True
        for r in rows:
            if r[0] == jid:
                return True
        return False

    def add_to_whitelist(self, jid):
        self.commit(
            'INSERT INTO whitelist VALUES (?)', (jid,))

    def remove_from_whitelist(self, jid):
        self.commit(
            'DELETE FROM whitelist WHERE channel=?', (jid,))