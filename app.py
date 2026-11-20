"""Servidor local del catálogo y del acceso de administración."""
import hashlib
import re
import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

import json
import secrets
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for, send_from_directory, flash
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent


def create_app(instance_path=None):
    app = Flask(__name__, static_folder=None,
                instance_path=str(instance_path or ROOT / 'instance'))
    private = Path(app.instance_path)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_file = private / 'session.key'
    if not key_file.exists():
        with key_file.open('x') as file:
            file.write(secrets.token_hex(32))
        key_file.chmod(0o600)
    app.config.update(
        SECRET_KEY=key_file.read_text(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        TRUSTED_HOSTS=['127.0.0.1', 'localhost'],
    )
    database = private / 'catalogo.sqlite3'

    def connect():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        return connection

    with connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS contenido (
                tipo TEXT NOT NULL, id TEXT NOT NULL, datos TEXT NOT NULL,
                PRIMARY KEY (tipo, id)
            );
            CREATE TABLE IF NOT EXISTS administrador (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                usuario TEXT NOT NULL, password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS intentos (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cantidad INTEGER NOT NULL, bloqueo_hasta REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS migraciones (nombre TEXT PRIMARY KEY);
        ''')
        if not db.execute('SELECT 1 FROM migraciones WHERE nombre = ?', ('inicial',)).fetchone():
            initial = json.loads((ROOT / 'datos-iniciales.json').read_text())
            for kind, items in initial.items():
                for item in items:
                    db.execute('INSERT INTO contenido VALUES (?, ?, ?)',
                               (kind, item['id'], json.dumps(item, ensure_ascii=False)))
            db.execute('INSERT INTO migraciones VALUES (?)', ('inicial',))
        db.execute('INSERT OR IGNORE INTO intentos VALUES (1, 0, 0)')
    database.chmod(0o600)

    def admin():
        with connect() as db:
            return db.execute('SELECT * FROM administrador WHERE id = 1').fetchone()

    @app.before_request
    def protect_forms():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        if request.path.startswith(('/admin/publicaciones', '/admin/equipos')) and not session.get('admin'):
            return redirect(url_for('login'))
        if request.method == 'POST':
            provided = request.form.get('csrf', '')
            if not secrets.compare_digest(provided, session['csrf']):
                abort(400, 'La sesión del formulario venció. Recarga la página.')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.path.startswith(('/admin', '/api')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/')
    @app.get('/index.html')
    def home():
        return send_from_directory(ROOT, 'index.html')

    # Solo estos archivos públicos se pueden descargar.
    @app.get('/<filename>')
    def public_file(filename):
        if filename not in ('styles.css', 'script.js', 'admin.css'):
            abort(404)
        return send_from_directory(ROOT, filename)

    @app.get('/marca/<filename>')
    def brand_asset(filename):
        if filename not in ('logo-rt.svg', 'icono-rt.svg'):
            abort(404)
        return send_from_directory(ROOT / 'marca', filename)

    @app.get('/Imagenes/<path:filename>')
    def image(filename):
        if Path(filename).suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            abort(404)
        return send_from_directory(ROOT / 'Imagenes', filename)

    @app.get('/api/contenido')
    def content():
        result = {'equipos': [], 'publicaciones': []}
        with connect() as db:
            for row in db.execute('SELECT tipo, datos FROM contenido ORDER BY rowid'):
                result[row['tipo']].append(json.loads(row['datos']))
        return result

    @app.route('/admin/configurar', methods=['GET', 'POST'])
    def setup():
        if admin():
            return redirect(url_for('login'))
        error = None
        if request.method == 'POST':
            username = request.form.get('usuario', '').strip()
            password = request.form.get('password', '')
            confirmation = request.form.get('confirmacion', '')
            if not 3 <= len(username) <= 80:
                error = 'El usuario debe tener entre 3 y 80 caracteres.'
            elif not 12 <= len(password) <= 256:
                error = 'La contraseña debe tener entre 12 y 256 caracteres.'
            elif password != confirmation:
                error = 'Las contraseñas deben coincidir.'
            else:
                with connect() as db:
                    saved = db.execute(
                        'INSERT OR IGNORE INTO administrador VALUES (1, ?, ?)',
                        (username, generate_password_hash(password)))
                    created = saved.rowcount == 1
                if created:
                    session.clear()
                    session['admin'] = True
                    session.permanent = True
                    return redirect(url_for('dashboard'))
                return redirect(url_for('login'))
        return render_template('acceso.html', setup=True, error=error)

    @app.route('/admin/entrar', methods=['GET', 'POST'])
    def login():
        account = admin()
        if account is None:
            return redirect(url_for('setup'))
        error = None
        if request.method == 'POST':
            with connect() as db:
                attempt = db.execute('SELECT * FROM intentos WHERE id = 1').fetchone()
                if attempt['bloqueo_hasta'] > time.time():
                    return render_template('acceso.html', setup=False,
                                           error='Espera unos minutos antes de intentar de nuevo.'), 429
                valid_password = check_password_hash(account['password_hash'], request.form.get('password', ''))
                if request.form.get('usuario', '').strip() == account['usuario'] and valid_password:
                    db.execute('UPDATE intentos SET cantidad = 0, bloqueo_hasta = 0 WHERE id = 1')
                    session.clear()
                    session['admin'] = True
                    session.permanent = True
                    return redirect(url_for('dashboard'))
                count = attempt['cantidad'] + 1
                blocked_until = time.time() + 300 if count >= 5 else 0
                db.execute('UPDATE intentos SET cantidad = ?, bloqueo_hasta = ? WHERE id = 1',
                           (0 if count >= 5 else count, blocked_until))
            error = 'Usuario o contraseña incorrectos.'
        return render_template('acceso.html', setup=False, error=error)

    @app.get('/admin')
    def dashboard():
        if not session.get('admin'):
            return redirect(url_for('login'))
        with connect() as db:
            counts = {row['tipo']: row['cantidad'] for row in db.execute(
                'SELECT tipo, COUNT(*) AS cantidad FROM contenido GROUP BY tipo')}
        return render_template('panel.html', counts=counts)

    def find_publication(publication_id):
        with connect() as db:
            row = db.execute(
                'SELECT datos FROM contenido WHERE tipo = ? AND id = ?',
                ('publicaciones', publication_id)).fetchone()
        if row is None:
            abort(404)
        return json.loads(row['datos'])

    @app.get('/admin/publicaciones')
    def publications_list():
        with connect() as db:
            rows = db.execute(
                'SELECT datos FROM contenido WHERE tipo = ? ORDER BY rowid DESC',
                ('publicaciones',)).fetchall()
        return render_template('publicaciones.html',
                               publicaciones=[json.loads(row['datos']) for row in rows])

    @app.route('/admin/publicaciones/nueva', methods=['GET', 'POST'])
    @app.route('/admin/publicaciones/<publication_id>/editar', methods=['GET', 'POST'])
    def publication_form(publication_id=None):
        publication = find_publication(publication_id) if publication_id else {
            'titulo': '', 'etiqueta': '', 'fecha': '', 'contenido': ''}
        original = json.dumps(publication, ensure_ascii=False)
        revision = hashlib.sha256(original.encode()).hexdigest()
        quitar_foto = False
        error = None
        if request.method == 'POST':
            for field in ('titulo', 'etiqueta', 'fecha', 'contenido', 'textoAlternativo'):
                publication[field] = request.form.get(field, '').strip()
            quitar_foto = request.form.get('quitar_foto') == 'si'
            photo = request.files.get('foto')
            has_photo = photo is not None and bool(photo.filename)
            if not 1 <= len(publication['titulo']) <= 120:
                error = 'Escribe un título de hasta 120 caracteres.'
            elif not 1 <= len(publication['etiqueta']) <= 50:
                error = 'Escribe una etiqueta de hasta 50 caracteres.'
            elif not 1 <= len(publication['contenido']) <= 3000:
                error = 'Escribe un contenido de hasta 3000 caracteres.'
            else:
                try:
                    parsed = date.fromisoformat(publication['fecha'])
                    if parsed.isoformat() != publication['fecha']:
                        raise ValueError()
                except ValueError:
                    error = 'Selecciona una fecha válida.'
            if error is None and publication_id and request.form.get('revision') != revision:
                error = 'Esta publicación cambió. Revisa los datos y vuelve a guardar.'
            if error is None and quitar_foto and has_photo:
                error = 'Elige reemplazar la foto o quitarla, una opción a la vez.'
            needs_alt = has_photo or (publication.get('imagen') and not quitar_foto)
            if error is None and needs_alt and not 1 <= len(publication['textoAlternativo']) <= 200:
                error = 'Describe la foto en un máximo de 200 caracteres.'
            new_path = None
            if error is None and has_photo:
                try:
                    publication['imagen'], new_path = save_photo(photo)
                except ValueError as invalid:
                    error = str(invalid)
            if error is None:
                if quitar_foto or not publication.get('imagen'):
                    publication['imagen'] = ''
                    publication['textoAlternativo'] = ''
                publication['id'] = publication_id or secrets.token_hex(16)
                serialized = json.dumps(publication, ensure_ascii=False)
                try:
                    with connect() as db:
                        if publication_id:
                            updated = db.execute(
                                'UPDATE contenido SET datos = ? WHERE tipo = ? AND id = ? AND datos = ?',
                                (serialized, 'publicaciones', publication_id, original))
                            if updated.rowcount == 0:
                                abort(409, 'La publicación cambió. Recarga el formulario antes de guardar.')
                        else:
                            db.execute('INSERT INTO contenido VALUES (?, ?, ?)',
                                       ('publicaciones', publication['id'], serialized))
                except Exception:
                    if new_path is not None:
                        new_path.unlink(missing_ok=True)
                    raise
                flash('Publicación guardada. Ya puedes verla en la página principal.')
                return redirect(url_for('publications_list'))
        return render_template('publicacion_form.html', publicacion=publication,
                               editando=publication_id is not None, error=error,
                               revision=revision, quitar_foto=quitar_foto)

    @app.route('/admin/publicaciones/<publication_id>/eliminar', methods=['GET', 'POST'])
    def publication_delete(publication_id):
        publication = find_publication(publication_id)
        if request.method == 'POST':
            with connect() as db:
                db.execute('DELETE FROM contenido WHERE tipo = ? AND id = ?',
                           ('publicaciones', publication_id))
            flash('Publicación eliminada.')
            return redirect(url_for('publications_list'))
        return render_template('publicacion_eliminar.html', publicacion=publication)

    CATEGORIES = {'bocinas': 'Bocinas', 'microfonos': 'Micrófonos', 'mezcladoras': 'Mezcladoras'}
    uploads = private / 'uploads'
    uploads.mkdir(exist_ok=True)

    @app.get('/fotos/<filename>')
    def uploaded_image(filename):
        if not re.fullmatch(r'[a-f0-9]{32}\.webp', filename):
            abort(404)
        return send_from_directory(uploads, filename)

    def find_equipment(equipment_id):
        with connect() as db:
            row = db.execute('SELECT datos FROM contenido WHERE tipo = ? AND id = ?',
                             ('equipos', equipment_id)).fetchone()
        if row is None:
            abort(404)
        return json.loads(row['datos'])

    def save_photo(upload):
        # Verificamos el contenido real y generamos un archivo nuevo sin metadatos.
        raw = upload.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise ValueError('La foto debe pesar como máximo 5 MB.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as source:
                    if source.format not in ('JPEG', 'PNG', 'WEBP'):
                        raise ValueError('Elige una foto JPG, PNG o WebP.')
                    if source.width * source.height > 20_000_000:
                        raise ValueError('La foto debe tener como máximo 20 megapíxeles.')
                    source.load()
                    normalized = ImageOps.exif_transpose(source).convert('RGBA')
                    normalized.thumbnail((1600, 1600))
                    clean = Image.new('RGBA', normalized.size)
                    clean.paste(normalized)
                    output = BytesIO()
                    clean.save(output, format='WEBP', quality=85)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as error:
            raise ValueError('No pudimos leer la foto. Elige otra imagen JPG, PNG o WebP.') from error
        filename = secrets.token_hex(16) + '.webp'
        path = uploads / filename
        try:
            path.write_bytes(output.getvalue())
        except OSError:
            path.unlink(missing_ok=True)
            raise
        return '/fotos/' + filename, path

    @app.get('/admin/equipos')
    def equipment_list():
        with connect() as db:
            rows = db.execute('SELECT datos FROM contenido WHERE tipo = ? ORDER BY rowid DESC',
                              ('equipos',)).fetchall()
        return render_template('equipos.html', equipos=[json.loads(row['datos']) for row in rows],
                               categorias=CATEGORIES)

    @app.route('/admin/equipos/nuevo', methods=['GET', 'POST'])
    @app.route('/admin/equipos/<equipment_id>/editar', methods=['GET', 'POST'])
    def equipment_form(equipment_id=None):
        equipment = find_equipment(equipment_id) if equipment_id else {
            'nombre': '', 'categoria': 'bocinas', 'descripcion': '',
            'textoAlternativo': '', 'imagen': ''}
        original = json.dumps(equipment, ensure_ascii=False)
        revision = hashlib.sha256(original.encode()).hexdigest()
        error = None
        if request.method == 'POST':
            for field in ('nombre', 'categoria', 'descripcion', 'textoAlternativo'):
                equipment[field] = request.form.get(field, '').strip()
            if not 1 <= len(equipment['nombre']) <= 120:
                error = 'Escribe un nombre de hasta 120 caracteres.'
            elif equipment['categoria'] not in CATEGORIES:
                error = 'Selecciona una categoría válida.'
            elif not 1 <= len(equipment['descripcion']) <= 1500:
                error = 'Escribe una descripción de hasta 1500 caracteres.'
            elif not 1 <= len(equipment['textoAlternativo']) <= 200:
                error = 'Describe la foto en un máximo de 200 caracteres.'
            elif equipment_id and request.form.get('revision') != revision:
                error = 'Este equipo cambió desde que abriste el formulario. Revisa los datos y vuelve a guardar.'
            photo = request.files.get('foto')
            has_photo = photo is not None and bool(photo.filename)
            if error is None and not equipment_id and not has_photo:
                error = 'Selecciona una foto para el nuevo equipo.'
            new_path = None
            if error is None and has_photo:
                try:
                    equipment['imagen'], new_path = save_photo(photo)
                except ValueError as invalid:
                    error = str(invalid)
            if error is None:
                equipment['id'] = equipment_id or secrets.token_hex(16)
                serialized = json.dumps(equipment, ensure_ascii=False)
                try:
                    with connect() as db:
                        if equipment_id:
                            updated = db.execute(
                                'UPDATE contenido SET datos = ? WHERE tipo = ? AND id = ? AND datos = ?',
                                (serialized, 'equipos', equipment_id, original))
                            if updated.rowcount == 0:
                                abort(409, 'El equipo cambió. Recarga el formulario antes de guardar.')
                        else:
                            db.execute('INSERT INTO contenido VALUES (?, ?, ?)',
                                       ('equipos', equipment['id'], serialized))
                except Exception:
                    if new_path is not None:
                        new_path.unlink(missing_ok=True)
                    raise
                flash('Equipo guardado. Ya puedes verlo en el catálogo.')
                return redirect(url_for('equipment_list'))
        return render_template('equipo_form.html', equipo=equipment, categorias=CATEGORIES,
                               editando=equipment_id is not None, error=error, revision=revision)

    @app.route('/admin/equipos/<equipment_id>/eliminar', methods=['GET', 'POST'])
    def equipment_delete(equipment_id):
        equipment = find_equipment(equipment_id)
        if request.method == 'POST':
            with connect() as db:
                db.execute('DELETE FROM contenido WHERE tipo = ? AND id = ?', ('equipos', equipment_id))
            flash('Equipo eliminado del catálogo.')
            return redirect(url_for('equipment_list'))
        return render_template('equipo_eliminar.html', equipo=equipment)

    @app.errorhandler(413)
    def upload_too_large(error):
        return render_template('error_tamano.html'), 413

    @app.post('/admin/salir')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5500, debug=False)
