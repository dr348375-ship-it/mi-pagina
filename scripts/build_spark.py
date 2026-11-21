"""Genera solo los archivos públicos de Spark, sin contraseñas ni base privada."""
import argparse
import json
import re
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def snapshot():
    database = ROOT / 'instance' / 'catalogo.sqlite3'
    if not database.exists():
        return json.loads((ROOT / 'datos-iniciales.json').read_text())
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    try:
        result = {'equipos': [], 'publicaciones': []}
        for kind, data in connection.execute('SELECT tipo, datos FROM contenido ORDER BY rowid'):
            result[kind].append(json.loads(data))
        return result
    finally:
        connection.close()


def build(preview=False, emulator=False):
    output = ROOT / ('preview-spark' if preview or emulator else 'hosting')
    output.mkdir(exist_ok=True)
    # Solo estos archivos y directorios pueden salir del proyecto.
    for name in ('styles.css','admin.css','script.js'):
        shutil.copy2(ROOT / name, output / name)
    for directory in ('Imagenes', 'marca'):
        shutil.copytree(ROOT / directory, output / directory, dirs_exist_ok=True)
    for file in (ROOT / 'spark').rglob('*'):
        if file.is_file():
            target = output / file.relative_to(ROOT / 'spark')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
    html = (ROOT / 'index.html').read_text().replace('<script src="script.js" defer></script>', '<script type="module" src="/public-spark.js"></script>')
    (output / 'index.html').write_text(html)
    if preview:
        (output / 'firebase-config.json').write_text('{"preview":true}\n')
    if emulator:
        (output / 'firebase-config.json').write_text(json.dumps({'projectId':'demo-rt-spark', 'apiKey':'demo-api-key', 'authDomain':'localhost', 'emulators':True, 'adminUid':'IJmZ8L55pRXL5RWTO67BV06N8Re2'}))
    content = snapshot()
    for kind, items in content.items():
        for order, item in enumerate(items):
            item['orden'] = order
            item['revision'] = 1
            item.setdefault('imagen', '')
            item.setdefault('textoAlternativo', '')
            image = item['imagen']
            if image.startswith('/fotos/'):
                filename = image.removeprefix('/fotos/')
                if not re.fullmatch(r'[a-f0-9]{32}\.webp', filename):
                    raise ValueError('Nombre de foto no válido.')
                shutil.copy2(ROOT / 'instance' / 'uploads' / filename, output / 'Imagenes' / filename)
                item['imagen'] = '/Imagenes/' + filename
            elif image:
                item['imagen'] = '/' + image.lstrip('/')
                if not re.fullmatch(r'/Imagenes/[a-zA-Z0-9._-]+\.(png|jpg|jpeg|webp)', item['imagen']):
                    raise ValueError('La foto no pertenece a la galería local.')
                if not (output / item['imagen'].lstrip('/')).is_file():
                    raise ValueError('Falta una foto del catálogo.')
            if not item['imagen']:
                item['textoAlternativo'] = ''
    gallery = [{'nombre': path.stem.replace('-', ' ').capitalize(), 'url': '/Imagenes/' + path.name}
               for path in sorted((output / 'Imagenes').iterdir())
               if path.is_file() and re.fullmatch(r'[a-zA-Z0-9._-]+\.(png|jpg|jpeg|webp)', path.name)]
    (output / 'galeria.json').write_text(json.dumps(gallery, ensure_ascii=False, indent=2))
    (output / 'contenido-inicial.json').write_text(json.dumps(content, ensure_ascii=False, indent=2))
    (output / '404.html').write_text('<!doctype html><html lang="es"><meta charset="utf-8"><title>Página no encontrada</title><h1>Página no encontrada</h1><a href="/">Volver a RT Producciones</a></html>')
    print(f'Preparados {sum(map(len, content.values()))} registros y {len(gallery)} fotos en {output.name}/. No se publicó nada.')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true', help='Solo catálogo local, sin conexión a Firebase.')
    parser.add_argument('--emulator', action='store_true', help='Pruebas locales con un proyecto demo, sin datos reales de Firebase.')
    args = parser.parse_args()
    build(args.preview, args.emulator)
