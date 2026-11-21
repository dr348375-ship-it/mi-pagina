import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app import create_app


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'RT_BACKEND': '', 'K_SERVICE': ''})
        self.env.start()
        self.app = create_app(self.temp.name)
        self.app.testing = True
        self.client = self.app.test_client()
        self.store = self.app.extensions['catalog_store']

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def post(self, url, **data):
        self.client.get('/admin/entrar')
        with self.client.session_transaction() as session:
            data['csrf'] = session['csrf']
        return self.client.post(url, data=data)

    def sign_in(self):
        result = self.post('/admin/configurar', usuario='testadmin', password='example-test-12345', confirmacion='example-test-12345')
        self.assertEqual(result.status_code, 302)

    def test_public_and_private_routes(self):
        with self.client.get('/') as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.client.get('/api/contenido').json['equipos']), 3)
        for url in ['/instance/catalogo.sqlite3', '/storage.py', '/.env']:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get('/admin/equipos').status_code, 302)
        self.assertEqual(self.client.post('/admin/configurar').status_code, 400)

    def test_login_throttle_and_persistence(self):
        self.sign_in()
        self.post('/admin/salir')
        for _ in range(5):
            self.assertEqual(self.post('/admin/entrar', usuario='testadmin', password='bad').status_code, 200)
        self.assertEqual(self.post('/admin/entrar', usuario='testadmin', password='example-test-12345').status_code, 429)
        reloaded = create_app(self.temp.name)
        self.assertEqual(reloaded.extensions['catalog_store'].admin()['usuario'], 'testadmin')

    def test_publication_crud_and_stale_update(self):
        self.sign_in()
        form = dict(titulo='Nueva', etiqueta='Evento', fecha='2026-11-19', contenido='Contenido de prueba')
        self.assertEqual(self.post('/admin/publicaciones/nueva', **form).status_code, 302)
        item = self.store.list('publicaciones')[-1]
        original = json.dumps(item, ensure_ascii=False)
        form['revision'] = hashlib.sha256(original.encode()).hexdigest()
        form['titulo'] = 'Actualizada'
        url = '/admin/publicaciones/' + item['id']
        self.assertEqual(self.post(url + '/editar', **form).status_code, 302)
        self.assertEqual(self.post(url + '/editar', **form).status_code, 200)
        self.assertFalse(self.store.save('publicaciones', item['id'], original, original))
        self.assertEqual(self.post(url + '/eliminar').status_code, 302)
        self.assertIsNone(self.store.get('publicaciones', item['id']))

    def test_equipment_photo_survives_restart(self):
        self.sign_in()
        photo = io.BytesIO()
        Image.new('RGB', (32, 32), 'yellow').save(photo, format='PNG')
        photo.seek(0)
        form = dict(nombre='Equipo nuevo', categoria='bocinas', descripcion='Prueba', textoAlternativo='Bocina', foto=(photo, 'foto.png'))
        self.assertEqual(self.post('/admin/equipos/nuevo', **form).status_code, 302)
        item = self.store.list('equipos')[-1]
        reloaded = create_app(self.temp.name).test_client()
        result = reloaded.get(item['imagen'])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.mimetype, 'image/webp')
        form['foto'] = (io.BytesIO(b'not an image'), 'invalid.png')
        self.assertEqual(self.post('/admin/equipos/nuevo', **form).status_code, 200)
        self.assertEqual(len(self.store.list('equipos')), 4)

    def test_cloud_settings_and_setup_disabled(self):
        with patch.dict(os.environ, {'RT_BACKEND': 'firestore', 'GOOGLE_CLOUD_PROJECT': 'test-project',
                                    'STORAGE_BUCKET': 'test-bucket', 'SECRET_KEY': 'x' * 64,
                                    'TRUSTED_HOSTS': 'test.web.app'}), \
             patch('app.FirestoreStore') as store, patch('app.CloudPhotos'):
            store.return_value.admin.return_value = None
            cloud = create_app(self.temp.name)
            client = cloud.test_client()
            self.assertEqual(client.get('/admin/configurar', base_url='https://test.web.app').status_code, 404)
            self.assertEqual(client.get('/admin/entrar', base_url='https://test.web.app').status_code, 503)
            self.assertEqual(client.get('/', base_url='https://evil.example').status_code, 400)
            self.assertTrue(cloud.config['SESSION_COOKIE_SECURE'])
            self.assertEqual(cloud.config['SESSION_COOKIE_NAME'], '__session')


if __name__ == '__main__':
    unittest.main()
