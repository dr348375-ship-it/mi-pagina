export const kinds = ['equipos', 'publicaciones'];
export function validateItem(kind, data, gallery) {
  const required = kind === 'equipos'
    ? {nombre:120, descripcion:1500} : {titulo:120, etiqueta:50, contenido:3000};
  for (const [key, max] of Object.entries(required)) {
    if (typeof data[key] !== 'string' || !data[key].trim() || data[key].length > max)
      throw new Error(`Revisa el campo ${key} (máximo ${max} caracteres).`);
  }
  if (kind === 'equipos' && !['bocinas','microfonos','mezcladoras'].includes(data.categoria))
    throw new Error('Selecciona una categoría válida.');
  if (kind === 'publicaciones') {
    const date = /^\d{4}-\d{2}-\d{2}$/.test(data.fecha) && new Date(`${data.fecha}T12:00:00Z`);
    if (!date || !Number.isFinite(date.getTime()) || date.toISOString().slice(0,10) !== data.fecha)
      throw new Error('Selecciona una fecha válida.');
  }
  if (data.imagen && !gallery.some(photo => photo.url === data.imagen))
    throw new Error('Elige una foto disponible en la galería.');
  if (kind === 'equipos' && !data.imagen) throw new Error('Selecciona una foto para el equipo.');
  if (data.imagen && (!data.textoAlternativo.trim() || data.textoAlternativo.length > 200))
    throw new Error('Describe la foto en un máximo de 200 caracteres.');
  if (!data.imagen) data.textoAlternativo = '';
  return data;
}
export function assertCurrent(current, original) {
  if (!current || current.revision !== original.revision)
    throw new Error('Este contenido cambió o fue eliminado. Cancela y actualiza la lista antes de continuar.');
}
