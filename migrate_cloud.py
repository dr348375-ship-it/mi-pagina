"""Importación inicial. Sin --apply solo valida los datos locales; no accede a Google."""
import argparse
import json
import re
import sqlite3
from pathlib import Path

PROJECT = 'rtproducciones-89ace'
ROOT = Path(__file__).resolve().parent


def read_snapshot(private):
    database = private / 'catalogo.sqlite3'
    db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN')
        account = db.execute('SELECT usuario, password_hash FROM administrador WHERE id=1').fetchone()
        if not account:
            raise ValueError('Primero crea el administrador local.')
        rows = [dict(row) for row in db.execute('SELECT rowid AS orden, tipo, id, datos FROM contenido ORDER BY rowid')]
    finally:
        db.close()
    if len(rows) > 450:
        raise ValueError('Esta importación inicial admite hasta 450 registros.')
    photos = {}
    for row in rows:
        if row['tipo'] not in ('equipos', 'publicaciones') or not row['id'] or '/' in row['id']:
            raise ValueError('Registro local inválido.')
        item = json.loads(row['datos'])
        if item['id'] != row['id']:
            raise ValueError('ID inconsistente.')
        image = item.get('imagen', '')
        if image.startswith('/fotos/'):
            filename = image.removeprefix('/fotos/')
            if not re.fullmatch(r'[a-f0-9]{32}\.webp', filename):
                raise ValueError('Nombre de foto inválido.')
            photos[filename] = (private / 'uploads' / filename).read_bytes()
    return dict(account), rows, photos


def migrate(account, rows, photos, bucket):
    from google.api_core.exceptions import PreconditionFailed
    from storage import FirestoreStore, CloudPhotos
    store = FirestoreStore(PROJECT)
    remote_photos = CloudPhotos(PROJECT, bucket)
    marker = store.private.document('migracion_inicial')
    admin_ref = store.private.document('administrador')
    if marker.get().exists or admin_ref.get().exists:
        raise ValueError('El destino ya contiene un administrador o una importación. No se sobrescribe.')
    for kind in ('equipos', 'publicaciones'):
        if list(store.client.collection('rt_' + kind).limit(1).stream()):
            raise ValueError('El catálogo de destino no está vacío. No se sobrescribe.')
    for filename, data in photos.items():
        try:
            remote_photos.write(filename, data)
        except PreconditionFailed:
            if remote_photos.read(filename) != data:
                raise ValueError('Existe una foto distinta con el mismo nombre.')
    # Las fotos se copian antes; todos los documentos se crean en un único lote.
    # Si falla, se puede reintentar sin sobrescribir fotos o documentos existentes.
    batch = store.client.batch()
    for row in rows:
        batch.create(store.ref(row['tipo'], row['id']), {'datos': row['datos'], 'orden': row['orden']})
    batch.create(admin_ref, account)
    batch.create(marker, {'completada': True, 'registros': len(rows), 'fotos': len(photos)})
    batch.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path, default=ROOT / 'instance')
    parser.add_argument('--bucket')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    account, rows, photos = read_snapshot(args.instance)
    print(f'Validación local: {len(rows)} registros, {len(photos)} fotos y un administrador.')
    if not args.apply:
        print('No se escribió nada en Google Cloud.')
        return
    if not args.bucket:
        parser.error('--apply requiere --bucket con el nombre verificado del bucket privado.')
    migrate(account, rows, photos, args.bucket)
    print(f'Importación inicial completada en {PROJECT}.')


if __name__ == '__main__':
    main()
