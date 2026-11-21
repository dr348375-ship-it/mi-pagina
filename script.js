async function cargarContenido() {
  const estado = document.querySelector("#estado-contenido");
  try {
    const cargarDatos = window.rtLoadContent || (async () => {
      const respuesta = await fetch('/api/contenido');
      if (!respuesta.ok) throw new Error('No se pudo cargar el contenido');
      return respuesta.json();
    });
    const { equipos, publicaciones } = await cargarDatos();
    // Datos que mostraremos en el catálogo.
    
    
    // Encontramos el espacio del catálogo y la plantilla.
    const contenedorEquipos = document.querySelector(".equipos");
    const plantillaEquipo = document.querySelector("#plantilla-equipo");
    
    // Construimos una tarjeta para cada equipo.
    equipos.forEach((equipo) => {
      const copia = plantillaEquipo.content.cloneNode(true);
      const tarjeta = copia.querySelector(".tarjeta");
      const foto = copia.querySelector(".foto-equipo");
    
      tarjeta.dataset.id = equipo.id;
      tarjeta.dataset.categoria = equipo.categoria;
    
      foto.src = equipo.imagen;
      foto.alt = equipo.textoAlternativo;
    
      copia.querySelector("h3").textContent = equipo.nombre;
      copia.querySelector("p").textContent = equipo.descripcion;
    
      contenedorEquipos.appendChild(copia);
    });
    // Buscamos los botones y las tarjetas del catálogo.
    const botonesFiltro = document.querySelectorAll(".filtros button");
    const tarjetas = document.querySelectorAll(".equipos .tarjeta");
    
    // Preparamos una acción para cada botón.
    botonesFiltro.forEach((boton) => {
      boton.addEventListener("click", () => {
        const categoriaElegida = boton.dataset.filtro;
    
        // Indicamos cuál de los botones está seleccionado.
        botonesFiltro.forEach((otroBoton) => {
          otroBoton.setAttribute(
            "aria-pressed",
            otroBoton === boton ? "true" : "false"
          );
        });
    
        // Mostramos únicamente los equipos que corresponden.
        tarjetas.forEach((tarjeta) => {
          const coincide =
            categoriaElegida === "todos" ||
            tarjeta.dataset.categoria === categoriaElegida;
    
          tarjeta.hidden = !coincide;
        });
      });
    });
    
    const enlacesCotizacion = document.querySelectorAll(".cotizar-equipo");
    
    enlacesCotizacion.forEach((enlace) => {
      const tarjeta = enlace.closest(".tarjeta");
      const nombre = tarjeta.querySelector("h3").textContent.trim();
    
      const destino = new URL(enlace.href);
      destino.searchParams.set("text", `Hola, me gustaría cotizar la renta de ${nombre}.`);
      enlace.href = destino.toString();
    });
    
    // Datos de las publicaciones.
    
    
    const contenedorPublicaciones = document.querySelector(
      ".lista-publicaciones"
    );
    const plantillaPublicacion = document.querySelector(
      "#plantilla-publicacion"
    );
    
    // Preparamos el formato de las fechas en español.
    const formatoFecha = new Intl.DateTimeFormat("es-MX", {
      day: "numeric",
      month: "long",
      year: "numeric"
    });
    
    publicaciones.forEach((publicacion) => {
      const copia = plantillaPublicacion.content.cloneNode(true);
      const articulo = copia.querySelector(".publicacion");
      const fecha = copia.querySelector("time");
    
      articulo.dataset.id = publicacion.id;
      const foto = copia.querySelector(".foto-publicacion");
      if (publicacion.imagen) {
        foto.src = publicacion.imagen;
        foto.alt = publicacion.textoAlternativo || publicacion.titulo;
        foto.hidden = false;
      }
    
      copia.querySelector(".etiqueta").textContent = publicacion.etiqueta;
      copia.querySelector("h3").textContent = publicacion.titulo;
      copia.querySelector("p").textContent = publicacion.contenido;
    
      fecha.dateTime = publicacion.fecha;
      fecha.textContent = formatoFecha.format(
        new Date(`${publicacion.fecha}T12:00:00`)
      );
    
      contenedorPublicaciones.appendChild(copia);
    });
    estado.textContent = "";
  } catch (error) {
    estado.textContent = "No pudimos cargar el catálogo. Recarga la página para intentarlo de nuevo.";
    console.error(error);
  }
}

cargarContenido();
