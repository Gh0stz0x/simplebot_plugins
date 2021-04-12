
import sqlite3
from typing import Optional


class DBManager:
    def __init__(self, db_path: str) -> None:
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.commit('''CREATE TABLE IF NOT EXISTS games
                       (p1 TEXT,
                        p2 TEXT,
                        gid INTEGER NOT NULL,
                        board TEXT,
                        black TEXT,
                        p1_wins INTEGER DEFAULT 0,
                        p2_wins INTEGER DEFAULT 0,
                        PRIMARY KEY(p1,p2))''')

    def execute(self, statement: str, args=()) -> sqlite3.Cursor:
        return self.db.execute(statement, args)

    def commit(self, statement: str, args=()) -> sqlite3.Cursor:
        with self.db:
            return self.db.execute(statement, args)

    def close(self) -> None:
        self.db.close()

    def add_game(self, p1: str, p2: str, gid: str, board: str,
                 black: str) -> None:
        p1, p2 = sorted([p1, p2])
        self.commit('INSERT INTO games VALUES (?,?,?,?,?)',
                    (p1, p2, gid, board, black))

    def delete_game(self, p1: str, p2: str) -> None:
        p1, p2 = sorted([p1, p2])
        self.commit('DELETE FROM games WHERE p1=? AND p2=?', (p1, p2))

    def set_game(self, p1: str, p2: str, board: str, black: str) -> None:
        p1, p2 = sorted([p1, p2])
        self.commit('UPDATE games SET board=?, black=? WHERE p1=? AND p2=?',
                    (board, black, p1, p2))

    def set_wins(self, p1: str, p2: str, winner: str) -> None:
        if winner == 'p1':
            self.commit('UPDATE games SET p1_wins = p1_wins + 1 WHERE p1=? AND p2=?',
                        (p1, p2))
        else: # p2
            self.commit('UPDATE games SET p2_wins = p2_wins + 1 WHERE p1=? AND p2=?',
                        (p1, p2))

    def set_board(self, p1: str, p2: str, board: Optional[str]) -> None:
        p1, p2 = sorted([p1, p2])
        self.commit(
            'UPDATE games SET board=? WHERE p1=? AND p2=?', (board, p1, p2))

    def get_game_by_gid(self, gid: int) -> Optional[sqlite3.Row]:
        return self.execute(
            'SELECT * FROM games WHERE gid=?', (gid,)).fetchone()

    def get_game_by_players(self, p1: str, p2: str) -> Optional[sqlite3.Row]:
        p1, p2 = sorted([p1, p2])
        return self.db.execute(
            'SELECT * FROM games WHERE p1=? AND p2=?', (p1, p2)).fetchone()
