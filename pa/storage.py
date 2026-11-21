"""SQLite store. Record payloads and vectors are AES-GCM encrypted per field.
Plaintext columns: id, kind, created_at. Audit log is plaintext but holds no content."""
import json
import sqlite3
import threading
import time
import uuid

from . import embed


class Store:
    def __init__(self, path, crypto):
        self.c = crypto
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        with self.lock:
            # Overwrite deleted rows with zeros; without this, "deleted" rows stayed in the
            # file's free pages (seen on phone after Delete ALL).
            self.db.execute("PRAGMA secure_delete = ON")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, kind TEXT, data BLOB, created_at REAL);
            CREATE TABLE IF NOT EXISTS vectors(id TEXT PRIMARY KEY, kind TEXT, vec BLOB);
            CREATE TABLE IF NOT EXISTS audit(id TEXT, ts REAL, action_type TEXT, approval TEXT,
                                             execution TEXT, detail TEXT);
            CREATE INDEX IF NOT EXISTS rk ON records(kind);""")
            self.db.commit()

    @staticmethod
    def _aad(kind, rid):
        return "rec:%s:%s" % (kind, rid)

    def put(self, kind, data, vector_text=None, rid=None):
        rid = rid or uuid.uuid4().hex
        blob = self.c.enc(json.dumps(data).encode(), self._aad(kind, rid))
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO records VALUES(?,?,?,?)", (rid, kind, blob, time.time()))
            if vector_text is not None:
                b = self.c.enc(embed.pack(embed.embed(vector_text)), "vec:" + rid)
                self.db.execute("INSERT OR REPLACE INTO vectors VALUES(?,?,?)", (rid, kind, b))
            self.db.commit()
        return rid

    def all(self, kind):
        with self.lock:
            rows = self.db.execute("SELECT id,data,created_at FROM records WHERE kind=? ORDER BY created_at",
                                   (kind,)).fetchall()
        return [dict(json.loads(self.c.dec(d, self._aad(kind, i))), id=i, created_at=t) for i, d, t in rows]

    def recent(self, kind, limit):
        """The newest `limit` records of a kind, oldest first."""
        with self.lock:
            rows = self.db.execute("SELECT id,data,created_at FROM records WHERE kind=? "
                                   "ORDER BY created_at DESC, rowid DESC LIMIT ?", (kind, int(limit))).fetchall()
        return [dict(json.loads(self.c.dec(d, self._aad(kind, i))), id=i, created_at=t) for i, d, t in reversed(rows)]

    def trim(self, kind, keep):
        """Delete all but the newest `keep` records of a kind. Returns how many were deleted."""
        with self.lock:
            n = self.db.execute("DELETE FROM records WHERE kind=? AND id NOT IN (SELECT id FROM records "
                                "WHERE kind=? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                                (kind, kind, int(keep))).rowcount
            self.db.commit()
        return n

    def delete_kind(self, kind):
        with self.lock:
            n = self.db.execute("DELETE FROM records WHERE kind=?", (kind,)).rowcount
            self.db.execute("DELETE FROM vectors WHERE kind=?", (kind,))
            self.db.commit()
        return n

    def get(self, rid):
        with self.lock:
            r = self.db.execute("SELECT kind FROM records WHERE id=?", (rid,)).fetchone()
        return next((x for x in self.all(r[0]) if x["id"] == rid), None) if r else None

    def update(self, rid, data, vector_text=None):
        with self.lock:
            r = self.db.execute("SELECT kind FROM records WHERE id=?", (rid,)).fetchone()
            if not r:
                return False
            self.put(r[0], data, vector_text, rid)
        return True

    def delete(self, rid):
        with self.lock:
            n = self.db.execute("DELETE FROM records WHERE id=?", (rid,)).rowcount
            self.db.execute("DELETE FROM vectors WHERE id=?", (rid,))
            self.db.commit()
        return n > 0

    def search(self, kind, query, k, min_score):
        qv = embed.embed(query)
        with self.lock:
            rows = self.db.execute("SELECT id,vec FROM vectors WHERE kind=?", (kind,)).fetchall()
        scored = []
        for i, b in rows:
            s = embed.cosine(qv, embed.unpack(self.c.dec(b, "vec:" + i)))
            if s >= min_score:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [(s, self.get(i)) for s, i in scored[:k]]

    def delete_all(self):
        with self.lock:
            for t in ("records", "vectors", "audit"):
                self.db.execute("DELETE FROM " + t)
            self.db.commit()
            self.db.execute("VACUUM")  # rebuild the file so no old pages survive

    def audit(self, action_id, action_type, approval, execution, detail=""):
        """Ids, types and states only. Never message bodies, contacts or note text."""
        with self.lock:
            self.db.execute("INSERT INTO audit VALUES(?,?,?,?,?,?)",
                            (action_id, time.time(), action_type, approval, execution, detail[:80]))
            self.db.commit()

    def audit_rows(self):
        with self.lock:
            return self.db.execute("SELECT * FROM audit ORDER BY ts").fetchall()
