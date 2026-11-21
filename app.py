"""Servidor local del catálogo y del acceso de administración."""
import hashlib
import re
import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

import json
import secrets
import os
from storage import SQLiteStore, FirestoreStore, LocalPhotos, CloudPhotos
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
    cloud = os.environ.get('RT_BACKEND') == 'firestore'
    if os.environ.get('K_SERVICE') and not cloud:
        raise RuntimeError('Cloud Run requiere RT_BACKEND=firestore.')
    key_file = private / 'session.key'
    if cloud:
        secret = os.environ.get('SECRET_KEY', '')
        if len(secret) < 32:
            raise RuntimeError('Configura SECRET_KEY con al menos 32 caracteres.')
    else:
        if not key_file.exists():
            with key_file.open('x') as file:
                file.write(secrets.token_hex(32))
            key_file.chmod(0o600)
        secret = key_file.read_text()
    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_NAME='__session',
        SESSION_COOKIE_SECURE=cloud,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        TRUSTED_HOSTS=os.environ['TRUSTED_HOSTS'].split(',') if cloud else ['127.0.0.1', 'localhost'],
    )
    store = FirestoreStore(os.environ['GOOGLE_CLOUD_PROJECT']) if cloud else SQLiteStore(private, ROOT)
    app.extensions['catalog_store'] = store
    photos = CloudPhotos(os.environ['GOOGLE_CLOUD_PROJECT'], os.environ['STORAGE_BUCKET']) if cloud else LocalPhotos(private)

    def admin():
        return store.admin()

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
        return {kind: store.list(kind) for kind in ('equipos', 'publicaciones')}

    @app.route('/admin/configurar', methods=['GET', 'POST'])
    def setup():
        if cloud:
            abort(404)
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
                created = store.create_admin(username, generate_password_hash(password))
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
            if cloud:
                abort(503, 'El administrador todavía no está configurado.')
            return redirect(url_for('setup'))
        error = None
        if request.method == 'POST':
            valid_password = check_password_hash(account['password_hash'], request.form.get('password', ''))
            valid = request.form.get('usuario', '').strip() == account['usuario'] and valid_password
            accepted = store.login_attempt(valid)
            if accepted == 'blocked':
                return render_template('acceso.html', setup=False,
                                       error='Espera unos minutos antes de intentar de nuevo.'), 429
            if accepted == 'ok':
                session.clear()
                session['admin'] = True
                session.permanent = True
                return redirect(url_for('dashboard'))
            error = 'Usuario o contraseña incorrectos.'
        return render_template('acceso.html', setup=False, error=error)

    @app.get('/admin')
    def dashboard():
        if not session.get('admin'):
            return redirect(url_for('login'))
        counts = {kind: len(store.list(kind)) for kind in ('equipos', 'publicaciones')}
        return render_template('panel.html', counts=counts)

    def find_publication(publication_id):
        item = store.get('publicaciones', publication_id)
        if item is None:
            abort(404)
        return item

    @app.get('/admin/publicaciones')
    def publications_list():
        return render_template('publicaciones.html', publicaciones=store.list('publicaciones', reverse=True))

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
                    if not store.save('publicaciones', publication['id'], serialized, original if publication_id else None):
                        abort(409, 'El contenido cambió. Recarga el formulario antes de guardar.')
                except Exception:
                    if new_path is not None:
                        photos.delete(new_path)
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
            store.delete('publicaciones', publication_id)
            flash('Publicación eliminada.')
            return redirect(url_for('publications_list'))
        return render_template('publicacion_eliminar.html', publicacion=publication)

    CATEGORIES = {'bocinas': 'Bocinas', 'microfonos': 'Micrófonos', 'mezcladoras': 'Mezcladoras'}

    @app.get('/fotos/<filename>')
    def uploaded_image(filename):
        if not re.fullmatch(r'[a-f0-9]{32}\.webp', filename):
            abort(404)
        data = photos.read(filename)
        if data is None:
            abort(404)
        return app.response_class(data, mimetype='image/webp')

    def find_equipment(equipment_id):
        item = store.get('equipos', equipment_id)
        if item is None:
            abort(404)
        return item

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
        photos.write(filename, output.getvalue())
        return '/fotos/' + filename, filename

    @app.get('/admin/equipos')
    def equipment_list():
        return render_template('equipos.html', equipos=store.list('equipos', reverse=True), categorias=CATEGORIES)

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
                    if not store.save('equipos', equipment['id'], serialized, original if equipment_id else None):
                        abort(409, 'El contenido cambió. Recarga el formulario antes de guardar.')
                except Exception:
                    if new_path is not None:
                        photos.delete(new_path)
                    raise
                flash('Equipo guardado. Ya puedes verlo en el catálogo.')
                return redirect(url_for('equipment_list'))
        return render_template('equipo_form.html', equipo=equipment, categorias=CATEGORIES,
                               editando=equipment_id is not None, error=error, revision=revision)

    @app.route('/admin/equipos/<equipment_id>/eliminar', methods=['GET', 'POST'])
    def equipment_delete(equipment_id):
        equipment = find_equipment(equipment_id)
        if request.method == 'POST':
            store.delete('equipos', equipment_id)
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
