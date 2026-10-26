"""Transactional per-player report snapshots; never rewrite unrelated reports."""
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager


class SeasonReportStore:
    def __init__(self, path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS reports(account TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(account,key))')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:
            db.close()

    def put(self, account, key, snapshot, *, only_missing=False):
        payload=json.dumps(snapshot,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        with self.connect() as db:
            command='INSERT OR IGNORE' if only_missing else 'INSERT OR REPLACE'
            db.execute(command+' INTO reports(account,key,payload) VALUES(?,?,?)',(account,key,payload))

    def load(self):
        result={}
        with self.connect() as db:
            for account,key,payload in db.execute('SELECT account,key,payload FROM reports'):
                result.setdefault(account,{})[key]=json.loads(payload)
        return result
