// Sin una conexión válida se muestra un error: no sustituimos datos guardados
// por una copia antigua, que podría volver a mostrar registros eliminados.
window.rtLoadContent = async () => {
  const configResponse = await fetch('/firebase-config.json', {cache: 'no-store'});
  if (!configResponse.ok) throw new Error('Configuración no disponible');
  const config = await configResponse.json();
  if (config.preview && ['localhost', '127.0.0.1'].includes(location.hostname)) {
    const response = await fetch('/contenido-inicial.json');
    if (!response.ok) throw new Error('Vista previa no disponible');
    return response.json();
  }
  const {connectFirebase, readCatalog} = await import('./firebase-client.js');
  const {db, dbSDK} = await connectFirebase();
  return readCatalog(db, dbSDK);
};
await import('./script.js');
