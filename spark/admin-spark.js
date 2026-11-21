import {connectFirebase, readCatalog} from './firebase-client.js';
import {validateItem, assertCurrent} from './catalog-model.mjs';
const $ = selector => document.querySelector(selector);
let connection, gallery = [], catalog = {equipos:[], publicaciones:[]};
let kind = 'equipos', editing = null, authorized = false, busy = false, authVersion = 0;
const fields = {equipos:['nombre','categoria','descripcion'], publicaciones:['titulo','etiqueta','fecha','contenido']};
function status(message, error = false) { $('#estado').textContent = message; $('#estado').classList.toggle('error', error); }
function describeError(error) {
  if (error.code?.startsWith('auth/')) {
    if (error.code === 'auth/too-many-requests') return 'Demasiados intentos. Espera unos minutos.';
    if (error.code === 'auth/network-request-failed') return 'No hay conexión. Inténtalo de nuevo.';
    if (error.code === 'auth/operation-not-allowed') return 'El acceso con correo todavía no está habilitado en Firebase.';
    return 'No pudimos iniciar sesión. Revisa tu correo y contraseña.';
  }
  if (error.code === 'permission-denied') return 'Tu cuenta no tiene permiso o falta configurar las reglas de acceso.';
  if (error.code === 'unavailable') return 'No hay conexión con la base de datos. No se confirmó el cambio; actualiza la lista antes de reintentarlo.';
  return error.message || 'No pudimos completar la operación. Inténtalo de nuevo.';
}
async function action(task, errorTarget = null) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => button.disabled = true);
  if (errorTarget) errorTarget.textContent = '';
  try { await task(); }
  catch (error) {
    const message = describeError(error);
    if (errorTarget) errorTarget.textContent = message; else status(message, true);
  } finally {
    busy = false;
    document.querySelectorAll('button').forEach(button => button.disabled = false);
  }
}
function showPhoto() {
  const url = $('#imagen').value;
  $('#vista-foto').hidden = !url;
  if (url) $('#vista-foto').src = url; else $('#vista-foto').removeAttribute('src');
  $('#textoAlternativo').required = Boolean(url);
}
function openEditor(item = null) {
  editing = item ? {...item} : null;
  $('#formulario').reset();
  for (const name of ['equipos','publicaciones']) {
    const block = $(`[data-fields="${name}"]`);
    block.hidden = name !== kind;
    block.querySelectorAll('input,textarea,select').forEach(input => {
      input.disabled = name !== kind;
      input.required = name === kind;
    });
  }
  for (const field of [...fields[kind], 'textoAlternativo']) if (item) $(`#${field}`).value = item[field] || '';
  if (!item && kind === 'publicaciones') {
    const today = new Date();
    $('#fecha').value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  }
  $('#imagen').replaceChildren();
  $('#imagen').append(new Option(kind === 'publicaciones' ? 'Sin foto' : 'Selecciona una foto', ''));
  gallery.forEach(photo => $('#imagen').append(new Option(photo.nombre, photo.url)));
  $('#imagen').required = kind === 'equipos';
  $('#imagen').value = item?.imagen || '';
  showPhoto();
  $('#error-formulario').textContent = '';
  $('#titulo-editor').textContent = `${item ? 'Editar' : 'Agregar'} ${kind === 'equipos' ? 'equipo' : 'publicación'}`;
  $('#panel').hidden = true; $('#editor').hidden = false; $('#titulo-editor').focus();
}
function closeEditor() { $('#editor').hidden = true; $('#panel').hidden = !authorized; editing = null; }
function renderList() {
  $('#lista').replaceChildren();
  $('#nuevo').textContent = kind === 'equipos' ? 'Agregar equipo' : 'Agregar publicación';
  document.querySelectorAll('[data-kind]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.kind === kind)));
  if (!catalog[kind].length) { const p = document.createElement('p'); p.textContent = 'Todavía no hay contenido en esta sección.'; $('#lista').append(p); }
  [...catalog[kind]].reverse().forEach(item => {
    const article = document.createElement('article'); article.className = 'admin-tarjeta';
    const title = document.createElement('h2'); title.textContent = item.nombre || item.titulo; article.append(title);
    if (item.imagen) { const img = document.createElement('img'); img.src = item.imagen; img.alt = item.textoAlternativo; img.loading = 'lazy'; article.append(img); }
    const description = document.createElement('p'); description.textContent = item.descripcion || item.contenido; article.append(description);
    const actions = document.createElement('div'); actions.className = 'admin-acciones';
    for (const [label, handler] of [['Editar', () => openEditor(item)], ['Eliminar', () => confirmDelete(item)]]) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'boton'; button.textContent = label;
      button.addEventListener('click', handler); actions.append(button);
    }
    article.append(actions); $('#lista').append(article);
  });
}
async function refresh() {
  const {db, dbSDK:sdk} = connection;
  const version = authVersion;
  const [loaded, imported] = await Promise.all([readCatalog(db, sdk), sdk.getDocFromServer(sdk.doc(db, 'configuracion', 'importacion'))]);
  if (version !== authVersion || !authorized) return;
  catalog = loaded;
  $('#importacion').hidden = imported.exists() || loaded.equipos.length + loaded.publicaciones.length > 0;
  renderList();
}
function confirmDelete(item) {
  const dialog = $('#confirmacion');
  $('#texto-eliminar').textContent = `¿Eliminar “${item.nombre || item.titulo}”?`;
  dialog.returnValue = 'cancelar';
  dialog.onclose = () => {
    if (dialog.returnValue !== 'eliminar') return;
    action(async () => {
      const {db, dbSDK:sdk} = connection;
      const ref = sdk.doc(db, kind, item.id);
      await sdk.runTransaction(db, async transaction => {
        const current = await transaction.get(ref);
        assertCurrent(current.exists() ? current.data() : null, item);
        transaction.delete(ref);
      });
      status('Contenido eliminado.'); await refresh();
    });
  };
  dialog.showModal();
}
$('#imagen').addEventListener('change', showPhoto);
$('#nuevo').addEventListener('click', () => openEditor());
$('#cancelar').addEventListener('click', closeEditor);
$('#recargar').addEventListener('click', () => action(async () => { await refresh(); status('Lista actualizada.'); }));
document.querySelectorAll('[data-kind]').forEach(button => button.addEventListener('click', () => {kind = button.dataset.kind; renderList();}));
$('#salir').addEventListener('click', () => action(() => connection.authSDK.signOut(connection.auth)));
$('#login').addEventListener('submit', event => {
  event.preventDefault();
  action(async () => {
    await connection.authSDK.signInWithEmailAndPassword(connection.auth, $('#correo').value.trim(), $('#clave').value);
    $('#clave').value = '';
  });
});
$('#formulario').addEventListener('submit', event => {
  event.preventDefault();
  action(async () => {
    if (!authorized) throw new Error('Inicia sesión de nuevo.');
    const {db, dbSDK:sdk} = connection;
    const data = Object.fromEntries([...fields[kind], 'imagen','textoAlternativo'].map(field => [field, $(`#${field}`).value.trim()]));
    validateItem(kind, data, gallery);
    const original = editing;
    const ref = original ? sdk.doc(db, kind, original.id) : sdk.doc(sdk.collection(db, kind));
    await sdk.runTransaction(db, async transaction => {
      const current = await transaction.get(ref);
      if (original) assertCurrent(current.exists() ? current.data() : null, original);
      else if (current.exists()) throw new Error('No se pudo crear el registro. Inténtalo de nuevo.');
      transaction.set(ref, {...data, orden: original?.orden ?? Date.now(), revision: (original?.revision ?? 0) + 1});
    });
    closeEditor(); status('Cambios guardados. Ya se muestran en la página principal.'); await refresh();
  }, $('#error-formulario'));
});
$('#importar').addEventListener('click', () => action(async () => {
  const {db, dbSDK:sdk} = connection;
  const response = await fetch('/contenido-inicial.json', {cache:'no-store'});
  if (!response.ok) throw new Error('No se encontró el contenido inicial.');
  const initial = await response.json();
  const records = ['equipos','publicaciones'].flatMap(type => initial[type].map(item => ({type, item})));
  if (records.length > 400) throw new Error('La importación requiere revisión por su tamaño.');
  records.forEach(({type, item}) => validateItem(type, item, gallery));
  const marker = sdk.doc(db, 'configuracion', 'importacion');
  await sdk.runTransaction(db, async transaction => {
    const done = await transaction.get(marker);
    const refs = records.map(({type, item}) => sdk.doc(db, type, item.id));
    const existing = await Promise.all(refs.map(ref => transaction.get(ref)));
    if (done.exists() || existing.some(snapshot => snapshot.exists())) throw new Error('Ya se importó contenido o hay registros con esos identificadores. No se reemplazó nada.');
    records.forEach(({item}, i) => {const {id, ...data} = item; transaction.set(refs[i], data);});
    transaction.set(marker, {completada:true});
  });
  status('Contenido inicial importado.'); await refresh();
}));
async function start() {
  try {
    const response = await fetch('/galeria.json');
    if (!response.ok) throw new Error('No se pudo cargar la galería.');
    gallery = await response.json();
    connection = await connectFirebase();
    connection.authSDK.onAuthStateChanged(connection.auth, async user => {
      const version = ++authVersion;
      authorized = false; catalog = {equipos:[], publicaciones:[]}; closeEditor(); $('#lista').replaceChildren();
      $('#acceso').hidden = Boolean(user); $('#sesion').hidden = !user;
      $('#confirmacion').close('cancelar');
      if (!user) {status('Inicia sesión para administrar el contenido.'); return;}
      $('#cuenta').textContent = user.email;
      try {
        if (version !== authVersion) return;
        if (user.uid !== connection.adminUid) throw new Error('Esta cuenta no está autorizada como administradora.');
        authorized = true; $('#panel').hidden = false;
        status('Sesión iniciada.'); await refresh();
      } catch(error) { if (version === authVersion) status(describeError(error), true); }
    });
  } catch(error) { status(describeError(error), true); }
}
start();
