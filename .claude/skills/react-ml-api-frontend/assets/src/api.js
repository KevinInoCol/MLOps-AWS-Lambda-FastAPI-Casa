// Cliente HTTP del backend de predicción (FastAPI en AWS Lambda u otro host).
// La URL se lee en BUILD time desde .env (VITE_API_URL). No es un secreto:
// todo lo que empieza con VITE_ queda visible en el JavaScript del navegador.

export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");
export const RUTA_PREDICCION =
  import.meta.env.VITE_RUTA_PREDICCION || "/obtener-datos-de-usuario-y-predecir";
export const COLUMNA_PREDICCION =
  import.meta.env.VITE_COLUMNA_PREDICCION || "Predicciones_Sin_Escalar";

const TIMEOUT_MS = 90_000; // Lambda puede tardar varios segundos en el cold start
export const LIMITE_BYTES = 5.5 * 1024 * 1024; // Lambda acepta hasta 6 MB por request

async function conTimeout(url, opciones = {}) {
  const controlador = new AbortController();
  const t = setTimeout(() => controlador.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, { ...opciones, signal: controlador.signal });
  } catch (e) {
    if (e.name === "AbortError") {
      throw new Error(`La API no respondió en ${TIMEOUT_MS / 1000} s. Reintenta: si fue cold start, la segunda vez es rápida.`);
    }
    // fetch lanza TypeError tanto si la API está caída como si el navegador bloquea por CORS
    throw new Error("No se pudo conectar con la API (¿está desplegada? ¿CORS habilitado para este origen?).");
  } finally {
    clearTimeout(t);
  }
}

async function detalleDeError(respuesta) {
  try {
    const cuerpo = await respuesta.json();
    return typeof cuerpo.detail === "string" ? cuerpo.detail : JSON.stringify(cuerpo.detail ?? cuerpo);
  } catch {
    return respuesta.statusText;
  }
}

/** GET / → { ok, mensaje } */
export async function estadoApi() {
  try {
    const r = await conTimeout(`${API_URL}/`);
    if (!r.ok) return { ok: false, mensaje: `Error ${r.status}` };
    const cuerpo = await r.json();
    return { ok: true, mensaje: cuerpo.mensaje ?? "OK" };
  } catch (e) {
    return { ok: false, mensaje: e.message };
  }
}

/** POST multipart (campo "file") → texto CSV con las predicciones */
export async function predecir(archivo) {
  const formulario = new FormData();
  // No pongas el header Content-Type a mano: el navegador agrega el boundary del multipart
  formulario.append("file", new File([archivo], archivo.name, { type: "text/csv" }));

  const r = await conTimeout(`${API_URL}${RUTA_PREDICCION}`, { method: "POST", body: formulario });
  if (!r.ok) throw new Error(`Error ${r.status}: ${await detalleDeError(r)}`);
  return r.text();
}
