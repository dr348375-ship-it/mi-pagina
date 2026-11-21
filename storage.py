"""Persistencia local y en Google Cloud, sin acceso público directo a los datos."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def next_attempt(current, valid):
    if current['bloqueo_hasta'] > time.time():
        return 'blocked', current
    if valid:
        return 'ok', {'cantidad': 0, 'bloqueo_hasta': 0}
    count = current['cantidad'] + 1
    return 'invalid', {'cantidad': 0 if count >= 5 else count,
                       'bloqueo_hasta': time.time() + 300 if count >= 5 else 0}


class SQLiteStore:
    def __init__(self, private, root):
        self.database = private / 'catalogo.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS contenido (
                    tipo TEXT NOT NULL, id TEXT NOT NULL, datos TEXT NOT NULL,
                    PRIMARY KEY (tipo, id));
                CREATE TABLE IF NOT EXISTS administrador (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    usuario TEXT NOT NULL, password_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS intentos (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cantidad INTEGER NOT NULL, bloqueo_hasta REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS migraciones (nombre TEXT PRIMARY KEY);
            ''')
            if not db.execute('SELECT 1 FROM migraciones WHERE nombre = ?', ('inicial',)).fetchone():
                initial = json.loads((root / 'datos-iniciales.json').read_text())
                for kind, items in initial.items():
                    for item in items:
                        db.execute('INSERT INTO contenido VALUES (?, ?, ?)',
                                   (kind, item['id'], json.dumps(item, ensure_ascii=False)))
                db.execute('INSERT INTO migraciones VALUES (?)', ('inicial',))
            db.execute('INSERT OR IGNORE INTO intentos VALUES (1, 0, 0)')
        self.database.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def admin(self):
        with self.connect() as db:
            row = db.execute('SELECT * FROM administrador WHERE id = 1').fetchone()
            return dict(row) if row else None

    def create_admin(self, username, password_hash):
        with self.connect() as db:
            return db.execute('INSERT OR IGNORE INTO administrador VALUES (1, ?, ?)',
                              (username, password_hash)).rowcount == 1

    def login_attempt(self, valid):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = dict(db.execute('SELECT * FROM intentos WHERE id = 1').fetchone())
            result, updated = next_attempt(current, valid)
            db.execute('UPDATE intentos SET cantidad = ?, bloqueo_hasta = ? WHERE id = 1',
                       (updated['cantidad'], updated['bloqueo_hasta']))
            return result

    def list(self, kind, reverse=False):
        with self.connect() as db:
            rows = db.execute('SELECT datos FROM contenido WHERE tipo = ? ORDER BY rowid', (kind,))
            items = [json.loads(row['datos']) for row in rows]
        return items[::-1] if reverse else items

    def get(self, kind, item_id):
        with self.connect() as db:
            row = db.execute('SELECT datos FROM contenido WHERE tipo = ? AND id = ?',
                             (kind, item_id)).fetchone()
            return json.loads(row['datos']) if row else None

    def save(self, kind, item_id, serialized, original=None):
        with self.connect() as db:
            if original is None:
                db.execute('INSERT INTO contenido VALUES (?, ?, ?)', (kind, item_id, serialized))
                return True
            return db.execute('UPDATE contenido SET datos = ? WHERE tipo = ? AND id = ? AND datos = ?',
                              (serialized, kind, item_id, original)).rowcount == 1

    def delete(self, kind, item_id):
        with self.connect() as db:
            db.execute('DELETE FROM contenido WHERE tipo = ? AND id = ?', (kind, item_id))


class FirestoreStore:
    def __init__(self, project):
        from google.cloud import firestore
        self.firestore = firestore
        self.client = firestore.Client(project=project)
        self.private = self.client.collection('rt_privado')

    def ref(self, kind, item_id):
        # El ID proviene también de una ruta HTTP, nunca permitir rutas anidadas.
        if not item_id or '/' in item_id or item_id in ('.', '..'):
            raise ValueError('ID inválido')
        return self.client.collection('rt_' + kind).document(item_id)

    def admin(self):
        return self.private.document('administrador').get().to_dict()

    def create_admin(self, username, password_hash):
        from google.api_core.exceptions import AlreadyExists
        try:
            self.private.document('administrador').create({'usuario': username, 'password_hash': password_hash})
            return True
        except AlreadyExists:
            return False

    def login_attempt(self, valid):
        ref = self.private.document('intentos')

        @self.firestore.transactional
        def update(transaction):
            current = ref.get(transaction=transaction).to_dict() or {'cantidad': 0, 'bloqueo_hasta': 0}
            result, updated = next_attempt(current, valid)
            transaction.set(ref, updated)
            return result
        return update(self.client.transaction())

    def list(self, kind, reverse=False):
        rows = [doc.to_dict() for doc in self.client.collection('rt_' + kind).stream()]
        rows.sort(key=lambda row: (row['orden'], json.loads(row['datos'])['id']), reverse=reverse)
        return [json.loads(row['datos']) for row in rows]

    def get(self, kind, item_id):
        row = self.ref(kind, item_id).get().to_dict()
        return json.loads(row['datos']) if row else None

    def save(self, kind, item_id, serialized, original=None):
        ref = self.ref(kind, item_id)

        @self.firestore.transactional
        def update(transaction):
            current = ref.get(transaction=transaction).to_dict()
            if original is None:
                if current is not None:
                    return False
                transaction.create(ref, {'datos': serialized, 'orden': time.time_ns()})
            else:
                if current is None or current['datos'] != original:
                    return False
                transaction.update(ref, {'datos': serialized})
            return True
        return update(self.client.transaction())

    def delete(self, kind, item_id):
        self.ref(kind, item_id).delete()


class LocalPhotos:
    def __init__(self, private):
        self.directory = private / 'uploads'
        self.directory.mkdir(exist_ok=True)

    def write(self, filename, data):
        path = self.directory / filename
        try:
            path.write_bytes(data)
        except OSError:
            path.unlink(missing_ok=True)
            raise

    def read(self, filename):
        try:
            return (self.directory / filename).read_bytes()
        except FileNotFoundError:
            return None

    def delete(self, filename):
        (self.directory / filename).unlink(missing_ok=True)


class CloudPhotos:
    def __init__(self, project, bucket):
        from google.cloud import storage
        self.bucket = storage.Client(project=project).bucket(bucket)

    def write(self, filename, data):
        self.bucket.blob('fotos/' + filename).upload_from_string(
            data, content_type='image/webp', if_generation_match=0)

    def read(self, filename):
        from google.api_core.exceptions import NotFound
        try:
            return self.bucket.blob('fotos/' + filename).download_as_bytes()
        except NotFound:
            return None

    def delete(self, filename):
        from google.api_core.exceptions import NotFound
        try:
            self.bucket.blob('fotos/' + filename).delete()
        except NotFound:
            pass
