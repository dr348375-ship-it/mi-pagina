import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {validateItem, assertCurrent} from '../spark/catalog-model.mjs';
const gallery = [{url:'/Imagenes/bocina-provisional.png'}];
const equipment = {nombre:'Bocina', categoria:'bocinas', descripcion:'Sonido', imagen:gallery[0].url, textoAlternativo:'Bocina negra'};
const publication = {titulo:'Evento', etiqueta:'Noticias', fecha:'2026-11-19', contenido:'Texto', imagen:'', textoAlternativo:''};
test('equipo válido y selección de fotos limitada', () => {
  assert.equal(validateItem('equipos', {...equipment}, gallery).nombre, 'Bocina');
  for (const imagen of ['', 'https://example.com/photo.png', '/Imagenes/no-existe.png'])
    assert.throws(() => validateItem('equipos', {...equipment, imagen}, gallery));
});
test('foto opcional en publicaciones y fechas reales', () => {
  assert.equal(validateItem('publicaciones', {...publication}, gallery).imagen, '');
  for (const fecha of ['2026-02-30', '2026-13-01', 'ayer'])
    assert.throws(() => validateItem('publicaciones', {...publication, fecha}, gallery));
});
test('rechaza cambios o eliminaciones sobre una versión vieja', () => {
  assertCurrent({revision:2}, {revision:2});
  assert.throws(() => assertCurrent({revision:3}, {revision:2}));
  assert.throws(() => assertCurrent(null, {revision:2}));
});
test('paquete de Hosting sin servidor ni credenciales privadas', () => {
  const config = JSON.parse(readFileSync('firebase.json'));
  assert.equal(config.hosting.public, 'hosting');
  assert.ok(!JSON.stringify(config).includes('"run"'));
  for (const path of ['instance', 'app.py', 'storage.py', 'session.key', '.env']) assert.ok(!existsSync('hosting/' + path));
  const initial = JSON.parse(readFileSync('hosting/contenido-inicial.json'));
  const photos = JSON.parse(readFileSync('hosting/galeria.json'));
  for (const kind of ['equipos','publicaciones']) for (const item of initial[kind]) validateItem(kind, item, photos);
  assert.ok(!readFileSync('hosting/contenido-inicial.json','utf8').includes('password_hash'));
});
