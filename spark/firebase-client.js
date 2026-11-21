// Configuración pública de la app. Los permisos se controlan con firestore.rules.
export async function connectFirebase() {
  const response = await fetch('/firebase-config.json', {cache: 'no-store'});
  if (!response.ok) throw new Error('No se pudo cargar la configuración.');
  const config = await response.json();
  if (config.preview) throw new Error('Esta vista previa no está conectada al administrador.');
  const [appSDK, authSDK, dbSDK] = await Promise.all([
    import('https://www.gstatic.com/firebasejs/13.4.0/firebase-app.js'),
    import('https://www.gstatic.com/firebasejs/13.4.0/firebase-auth.js'),
    import('https://www.gstatic.com/firebasejs/13.4.0/firebase-firestore.js')
  ]);
  const app = appSDK.initializeApp(config);
  const auth = authSDK.getAuth(app);
  const db = dbSDK.getFirestore(app);
  if (config.emulators) {
    if (!['localhost', '127.0.0.1'].includes(location.hostname) || !config.projectId.startsWith('demo-'))
      throw new Error('Los emuladores solo se permiten en una vista previa local.');
    authSDK.connectAuthEmulator(auth, 'http://127.0.0.1:9098', {disableWarnings:true});
    dbSDK.connectFirestoreEmulator(db, '127.0.0.1', 8085);
  }
  await authSDK.setPersistence(auth, authSDK.browserSessionPersistence);
  return {auth, db, authSDK, dbSDK, adminUid: config.adminUid};
}

export async function readCatalog(db, sdk) {
  const kinds = ['equipos', 'publicaciones'];
  const lists = await Promise.all(kinds.map(async kind => {
    const snapshot = await sdk.getDocsFromServer(sdk.collection(db, kind));
    return snapshot.docs.map(doc => ({...doc.data(), id: doc.id}))
      .sort((a, b) => a.orden - b.orden || a.id.localeCompare(b.id));
  }));
  return Object.fromEntries(kinds.map((kind, i) => [kind, lists[i]]));
}
