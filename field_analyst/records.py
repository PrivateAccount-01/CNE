"""Durable offline plant records with transactionally retained original image bytes."""
import json, sqlite3, uuid
from datetime import datetime, timezone
from field_analyst.dataset import digest, image_rgb
from field_analyst import WARNING

class Records:
    def __init__(self,path):
        self.db=sqlite3.connect(str(path)); self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS plants(id TEXT PRIMARY KEY,name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,plant_id TEXT NOT NULL REFERENCES plants(id),
        captured_at TEXT NOT NULL,image BLOB NOT NULL,image_sha256 TEXT NOT NULL,note TEXT NOT NULL,result TEXT);''')
    def close(self): self.db.close()
    def create_plant(self,name):
        if not name.strip(): raise ValueError('Plant name required')
        pid=uuid.uuid4().hex
        with self.db: self.db.execute('INSERT INTO plants VALUES (?,?)',(pid,name.strip()))
        return pid
    def add(self,plant,image,note=''):
        image_rgb(image); oid=uuid.uuid4().hex
        with self.db: self.db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,NULL)',(oid,plant,datetime.now(timezone.utc).isoformat(),image,digest(image),note))
        return oid
    def update_note(self,oid,note):
        with self.db:
            if not self.db.execute('UPDATE observations SET note=? WHERE id=?',(note,oid)).rowcount: raise KeyError(oid)
    def analyze(self,oid,engine):
        row=self.db.execute('SELECT image,image_sha256,note FROM observations WHERE id=?',(oid,)).fetchone()
        if row is None: raise KeyError(oid)
        data,sha,note=row
        if digest(data)!=sha: raise ValueError('Stored photo integrity failure')
        result=engine.analyze(data,note)
        # Notes stay separate: previous model output is never rewritten as a causal observation.
        with self.db: self.db.execute('UPDATE observations SET result=? WHERE id=?',(json.dumps(result),oid))
        return result
    def history(self,plant):
        return [dict(id=r[0],captured_at=r[1],image_sha256=r[2],note=r[3],result=json.loads(r[4]) if r[4] else None,warning=WARNING)
                for r in self.db.execute('SELECT id,captured_at,image_sha256,note,result FROM observations WHERE plant_id=? ORDER BY captured_at,id',(plant,))]
