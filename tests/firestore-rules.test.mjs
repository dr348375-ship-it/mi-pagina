import {test, before, after, beforeEach} from 'node:test';
import {readFileSync} from 'node:fs';
import {initializeTestEnvironment, assertFails, assertSucceeds} from '@firebase/rules-unit-testing';
import {doc, setDoc, getDoc, updateDoc, deleteDoc, collection, getDocs} from 'firebase/firestore';
let env;
const equipment = {nombre:'Bocina', categoria:'bocinas', descripcion:'Sonido', imagen:'/Imagenes/bocina-provisional.png', textoAlternativo:'Bocina negra', orden:1, revision:1};
before(async () => {
  env = await initializeTestEnvironment({projectId:'demo-rt-spark', firestore:{host:'127.0.0.1', port:8085, rules:readFileSync('firestore.rules','utf8')}});
});
after(async () => {await env?.cleanup();});
beforeEach(async () => {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async context => {
    await setDoc(doc(context.firestore(),'administradores','admin'), {activo:true});
    await setDoc(doc(context.firestore(),'equipos','bocina'), equipment);
    await setDoc(doc(context.firestore(),'rt_privado','administrador'), {password_hash:'private-test-value'});
  });
});
test('visitantes leen catálogo pero no pueden modificarlo ni leer datos privados', async () => {
  const db = env.unauthenticatedContext().firestore();
  await assertSucceeds(getDocs(collection(db,'equipos')));
  await assertFails(setDoc(doc(db,'equipos','nuevo'),equipment));
  await assertFails(deleteDoc(doc(db,'equipos','bocina')));
  await assertFails(getDoc(doc(db,'rt_privado','administrador')));
  await assertFails(getDoc(doc(db,'administradores','admin')));
});
test('otro usuario no puede escribir ni otorgarse permisos', async () => {
  const db = env.authenticatedContext('otro').firestore();
  await assertFails(setDoc(doc(db,'equipos','nuevo'),equipment));
  await assertFails(setDoc(doc(db,'administradores','otro'),{activo:true}));
  await assertFails(updateDoc(doc(db,'administradores','admin'),{activo:true}));
});
test('administrador puede crear, editar y eliminar; valida campos y revisión', async () => {
  const db = env.authenticatedContext('IJmZ8L55pRXL5RWTO67BV06N8Re2').firestore();
  await assertSucceeds(setDoc(doc(db,'equipos','nuevo'),equipment));
  await assertSucceeds(updateDoc(doc(db,'equipos','nuevo'),{nombre:'Otra bocina', revision:2}));
  await assertFails(updateDoc(doc(db,'equipos','nuevo'),{nombre:'Sin revisión'}));
  await assertFails(updateDoc(doc(db,'equipos','nuevo'),{revision:3, imagen:'https://example.com/x.png'}));
  await assertFails(setDoc(doc(db,'equipos','invalido'),{...equipment, categoria:'otra'}));
  await assertFails(setDoc(doc(db,'equipos','extra'),{...equipment, secreto:'extra'}));
  await assertSucceeds(deleteDoc(doc(db,'equipos','nuevo')));
});
test('publicación puede no tener foto y la importación es única', async () => {
  const db = env.authenticatedContext('IJmZ8L55pRXL5RWTO67BV06N8Re2').firestore();
  await assertSucceeds(setDoc(doc(db,'publicaciones','evento'),{titulo:'Evento',etiqueta:'Noticias',fecha:'2026-11-19',contenido:'Información',imagen:'',textoAlternativo:'',orden:1,revision:1}));
  await assertSucceeds(setDoc(doc(db,'configuracion','importacion'),{completada:true}));
  await assertFails(setDoc(doc(db,'configuracion','importacion'),{completada:true}));
  await assertFails(deleteDoc(doc(db,'configuracion','importacion')));
});
