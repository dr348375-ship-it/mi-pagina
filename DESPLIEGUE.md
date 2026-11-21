# RT Producciones en Firebase Spark

Proyecto: `rtproducciones-89ace`. La versión web usa Firebase Hosting, Authentication con correo/contraseña y Firestore. No usa Cloud Run ni Cloud Storage. El plan permanece en Spark; las cuotas gratuitas siguen siendo aplicables.

## Estado actual

- App web registrada como **RT Producciones Web**; configuración pública en `spark/firebase-config.json`.
- Panel preparado para equipos y publicaciones, con fotos seleccionadas de una galería incluida al publicar.
- Reglas verificadas con el emulador de Firestore: visitantes y usuarios sin permiso no pueden escribir ni acceder a datos privados. Nadie puede asignarse permisos desde la página.
- Inicio de sesión, importación, edición y creación probados en el navegador con una cuenta ficticia en emuladores. El propietario proporcionó el UID de la cuenta real; ya está fijado en las reglas y la configuración. Publicado el 19 de noviembre de 2026 en https://rtproducciones-89ace.web.app. Reglas desplegadas y cinco registros iniciales importados.
- Los datos locales de SQLite y el administrador de Flask permanecen en la Mac. La cuenta de Firebase es independiente; su contraseña se configura en Firebase, nunca se copia el hash de SQLite al navegador.

## Preparar los archivos públicos

```sh
python3 scripts/build_spark.py
```

Se genera `hosting/` con una lista limitada de archivos. El catálogo inicial se exporta de la base SQLite existente; si no existe, se usan los datos iniciales. Solo se exportan equipos, publicaciones y fotos: no usuarios, contraseñas, claves de sesión ni el archivo de base de datos. La galería incluye las imágenes de `Imagenes/` y las fotos locales referenciadas por el catálogo.

Para añadir fotos en el futuro, coloca los archivos en `Imagenes/` con nombres sin espacios ni acentos y extensión `.png`, `.jpg`, `.jpeg` o `.webp`; vuelve a preparar y publicar. Después aparecerán en el selector del panel. Las fotos forman parte del sitio público.

## Configuración y futuras publicaciones

1. En Authentication, habilitar el proveedor **Correo electrónico/contraseña**. Crear la cuenta del administrador desde **Usuarios > Agregar usuario**. La contraseña la introduce el propietario directamente, sin enviarla al chat.
2. Crear Firestore **Standard, modo nativo**, base `(default)`, en modo producción (acceso cerrado). Elegir una ubicación adecuada antes de crearla, ya que después no se puede cambiar. No seleccionar Enterprise ni pruebas con acceso abierto.
3. Administrador autorizado: `IJmZ8L55pRXL5RWTO67BV06N8Re2`. Está fijado en `firestore.rules` y `spark/firebase-config.json`; no hace falta crear documentos de permisos. Para cambiar de administrador hay que actualizar ambos archivos y volver a desplegar las reglas y Hosting.
4. Autenticar Firebase CLI con una cuenta con acceso a este proyecto (`firebase login`).
5. Publicar primero las reglas: `firebase deploy --only firestore:rules --project rtproducciones-89ace`.
6. Preparar y publicar Hosting: `firebase deploy --only hosting --project rtproducciones-89ace`. El paso previo genera automáticamente `hosting/`; no usar la raíz del proyecto como carpeta pública.
7. La importación inicial ya se completó desde la cuenta propietaria, sin sobrescribir datos. En una instalación nueva, en `https://rtproducciones-89ace.web.app/admin`, iniciar sesión y pulsar **Importar contenido inicial** una sola vez. La importación rechaza registros existentes con los mismos identificadores y conserva un marcador para impedir repeticiones. No es una herramienta de sincronización: los cambios posteriores se hacen en el panel.
8. Verificar la página pública, iniciar/cerrar sesión, editar y volver a cargar. Confirmar también que una cuenta no autorizada no puede modificar datos.

La configuración del SDK (incluida `apiKey`) es pública por diseño. La protección se aplica con Authentication y `firestore.rules`. No añadir claves de cuentas de servicio a `spark/` o `hosting/`.

## Pruebas

Con Node.js y pnpm disponibles:

```sh
pnpm install
python3 scripts/build_spark.py
pnpm test
pnpm run test:rules
.venv/bin/python -m unittest discover -s tests -v
```

Las reglas usan un proyecto demo sin conexión a producción. El emulador necesita Java 21. En esta Mac se descargó un runtime aislado en `.tools/java/Contents/Home`; no se cambió el Java del sistema. Las dependencias están en `node_modules/` y no se publican.

Vista previa del catálogo sin conexión a Firebase:

```sh
python3 scripts/build_spark.py --preview
python3 -m http.server 5501 --bind 127.0.0.1 --directory preview-spark
```

El panel muestra que no está conectado en esa vista. Para pruebas integradas, `--emulator` genera una configuración demo únicamente en `preview-spark/`; se necesitan emuladores de Auth en 9098 y Firestore en 8085, y una cuenta ficticia con el UID autorizado en las reglas. Esa configuración nunca se copia a Hosting.

## Compatibilidad con el proyecto anterior

`app.py`, `storage.py`, `templates/` e `instance/` siguen permitiendo usar el servidor local anterior. Los archivos `Dockerfile`, `requirements-cloud.txt` y `migrate_cloud.py` pertenecen a la propuesta anterior de Blaze y **no se usan para Spark**. `firebase.json` ya no contiene redirecciones a Cloud Run.

Referencias: [Firebase web](https://firebase.google.com/docs/web/setup), [reglas de Firestore](https://firebase.google.com/docs/firestore/security/get-started), [planes de Firebase](https://firebase.google.com/docs/projects/billing/firebase-pricing-plans).

## Repositorio principal

Desde el 20 de noviembre de 2026, el repositorio principal es `https://github.com/dr348375-ship-it/mi-pagina.git`, rama `main` y remoto `origin`. Por indicación del propietario, los próximos cambios del proyecto se guardan y se suben allí. El repositorio anterior `Tomilyk/RT_Producciones` queda como referencia en el remoto `anterior`. Subir a GitHub no publica automáticamente los cambios en Firebase; la publicación usa los comandos descritos arriba.
