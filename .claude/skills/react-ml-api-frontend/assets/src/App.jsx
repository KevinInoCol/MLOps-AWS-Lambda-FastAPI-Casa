import { useEffect, useMemo, useState } from "react";
import Papa from "papaparse";
import { API_URL, COLUMNA_PREDICCION, LIMITE_BYTES, RUTA_PREDICCION, estadoApi, predecir } from "./api";
import "./App.css";

const moneda = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const FILAS_VISIBLES = 50;

function leerCsv(texto) {
  const { data, meta } = Papa.parse(texto.trim(), { header: true, dynamicTyping: true, skipEmptyLines: true });
  return { filas: data, columnas: meta.fields ?? [] };
}

function Tabla({ columnas, filas, destacada }) {
  const orden = destacada && columnas.includes(destacada) ? [destacada, ...columnas.filter((c) => c !== destacada)] : columnas;
  return (
    <div className="tabla">
      <table>
        <thead>
          <tr>{orden.map((c) => <th key={c} className={c === destacada ? "dest" : ""}>{c === destacada ? "Precio estimado" : c}</th>)}</tr>
        </thead>
        <tbody>
          {filas.slice(0, FILAS_VISIBLES).map((fila, i) => (
            <tr key={i}>
              {orden.map((c) => (
                <td key={c} className={c === destacada ? "dest" : ""}>
                  {c === destacada && typeof fila[c] === "number" ? moneda.format(fila[c]) : String(fila[c] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {filas.length > FILAS_VISIBLES && <p className="nota">Mostrando {FILAS_VISIBLES} de {filas.length} filas. Descarga el CSV para verlas todas.</p>}
    </div>
  );
}

export default function App() {
  const [estado, setEstado] = useState({ cargando: true, ok: false, mensaje: "" });
  const [archivo, setArchivo] = useState(null);
  const [vistaPrevia, setVistaPrevia] = useState(null);
  const [resultado, setResultado] = useState(null); // { texto, filas, columnas }
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState("");

  const comprobar = async () => {
    setEstado({ cargando: true, ok: false, mensaje: "" });
    setEstado({ cargando: false, ...(await estadoApi()) });
  };

  useEffect(() => { comprobar(); }, []);

  const alElegir = async (e) => {
    const f = e.target.files?.[0];
    setResultado(null);
    setError("");
    setArchivo(f ?? null);
    setVistaPrevia(f ? leerCsv(await f.text()) : null);
  };

  const alPredecir = async () => {
    setEnviando(true);
    setError("");
    try {
      const texto = await predecir(archivo);
      setResultado({ texto, ...leerCsv(texto) });
    } catch (e) {
      setError(e.message);
    } finally {
      setEnviando(false);
    }
  };

  const resumen = useMemo(() => {
    const precios = resultado?.filas.map((f) => f[COLUMNA_PREDICCION]).filter((v) => typeof v === "number") ?? [];
    if (!precios.length) return null;
    return {
      n: precios.length,
      promedio: precios.reduce((a, b) => a + b, 0) / precios.length,
      min: Math.min(...precios),
      max: Math.max(...precios),
    };
  }, [resultado]);

  const descargar = () => {
    const url = URL.createObjectURL(new Blob([resultado.texto], { type: "text/csv" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "predicciones.csv" });
    a.click();
    URL.revokeObjectURL(url);
  };

  const muyGrande = archivo && archivo.size > LIMITE_BYTES;

  return (
    <div className="app">
      <header className="cabecera">
        <div>
          <h1>Predicción del precio de casas</h1>
          <p>Sube un CSV con las características de las casas y el modelo devolverá el precio estimado de cada una.</p>
        </div>
        <div className={`estado ${estado.cargando ? "esperando" : estado.ok ? "ok" : "caido"}`} title={API_URL}>
          <span className="punto" />
          {estado.cargando ? "Comprobando API…" : estado.ok ? "API en línea" : "API no disponible"}
          {!estado.cargando && <button className="enlace" onClick={comprobar}>Reintentar</button>}
        </div>
      </header>
      {!estado.cargando && !estado.ok && <p className="alerta">{estado.mensaje}</p>}

      <section className="panel">
        <label className="subir">
          <input type="file" accept=".csv,text/csv" onChange={alElegir} />
          <span>{archivo ? archivo.name : "Elegir archivo CSV"}</span>
        </label>
        {archivo && (
          <p className="nota">
            {vistaPrevia?.filas.length ?? 0} filas · {vistaPrevia?.columnas.length ?? 0} columnas · {(archivo.size / 1048576).toFixed(2)} MB
          </p>
        )}
        {muyGrande && <p className="alerta">El archivo pesa más de ~6 MB, el límite de Lambda por request. Divídelo en partes.</p>}
        <button className="primario" disabled={!archivo || muyGrande || enviando} onClick={alPredecir}>
          {enviando ? "Prediciendo… (la primera vez puede tardar)" : "Predecir"}
        </button>
        {error && <p className="alerta">{error}</p>}
      </section>

      {resultado && (
        <section className="panel">
          <div className="titulo-seccion">
            <h2>Predicciones</h2>
            <button className="secundario" onClick={descargar}>Descargar CSV</button>
          </div>
          {resumen && (
            <div className="metricas">
              <div><span>Casas</span><b>{resumen.n}</b></div>
              <div><span>Precio promedio</span><b>{moneda.format(resumen.promedio)}</b></div>
              <div><span>Mínimo</span><b>{moneda.format(resumen.min)}</b></div>
              <div><span>Máximo</span><b>{moneda.format(resumen.max)}</b></div>
            </div>
          )}
          <Tabla columnas={resultado.columnas} filas={resultado.filas} destacada={COLUMNA_PREDICCION} />
        </section>
      )}

      {vistaPrevia && !resultado && (
        <section className="panel">
          <h2>Datos subidos</h2>
          <Tabla columnas={vistaPrevia.columnas} filas={vistaPrevia.filas} />
        </section>
      )}

      <footer className="pie">Backend: <code>{API_URL}</code> · <code>POST {RUTA_PREDICCION}</code></footer>
    </div>
  );
}
