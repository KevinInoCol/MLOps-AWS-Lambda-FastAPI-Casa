"""Frontend en Streamlit que consume la API de predicción (FastAPI en AWS Lambda u otro host)."""

import io
import os

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# URL base del backend (sin "/" final). Local: http://localhost:8000 · Lambda: la Function URL
API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
RUTA_PREDICCION = os.getenv("RUTA_PREDICCION", "/obtener-datos-de-usuario-y-predecir")
COLUMNA_PREDICCION = os.getenv("COLUMNA_PREDICCION", "Predicciones_Sin_Escalar")

TIMEOUT_S = 90                    # Lambda puede tardar varios segundos en el cold start
LIMITE_MB = 5.5                   # Lambda acepta hasta 6 MB por request (margen para el multipart)


@st.cache_data(ttl=30, show_spinner=False)
def estado_api(url: str) -> tuple[bool, str]:
    """GET / del backend. Se cachea 30 s para no llamar a la API en cada rerun."""
    try:
        r = requests.get(f"{url}/", timeout=TIMEOUT_S)
        r.raise_for_status()
        return True, r.json().get("mensaje", "OK")
    except requests.RequestException as e:
        return False, str(e)


def predecir(url: str, nombre: str, contenido: bytes) -> pd.DataFrame:
    """Envía el CSV como multipart/form-data (campo 'file') y devuelve el CSV de respuesta."""
    r = requests.post(
        f"{url}{RUTA_PREDICCION}",
        files={"file": (nombre, contenido, "text/csv")},
        timeout=TIMEOUT_S,
    )
    if r.status_code != 200:
        try:
            detalle = r.json().get("detail", r.text)
        except ValueError:
            detalle = r.text
        raise RuntimeError(f"Error {r.status_code}: {detalle}")
    return pd.read_csv(io.BytesIO(r.content))


# ---------------------------------------------------------------- interfaz
st.set_page_config(page_title="Predicción de precios", page_icon="🏠", layout="wide")

with st.sidebar:
    st.header("Backend")
    st.code(API_URL, language=None)
    ok, mensaje = estado_api(API_URL)
    if ok:
        st.success(f"API en línea · {mensaje}")
    else:
        st.error("No se pudo conectar con la API")
        st.caption(mensaje)
    if st.button("Volver a comprobar"):
        estado_api.clear()
        st.rerun()
    st.divider()
    st.caption(f"Endpoint: `POST {RUTA_PREDICCION}`")
    st.caption("La primera llamada a Lambda puede tardar unos segundos (cold start).")

st.title("🏠 Predicción del precio de casas")
st.write("Sube un CSV con las características de las casas y el modelo devolverá el precio estimado de cada una.")

archivo = st.file_uploader("Archivo CSV", type=["csv"])

if archivo is not None:
    contenido = archivo.getvalue()
    tamano_mb = len(contenido) / 1_048_576

    try:
        vista_previa = pd.read_csv(io.BytesIO(contenido))
    except Exception:
        st.error("El archivo no es un CSV válido.")
        st.stop()

    st.subheader("Datos subidos")
    st.caption(f"{len(vista_previa)} filas · {vista_previa.shape[1]} columnas · {tamano_mb:.2f} MB")
    st.dataframe(vista_previa.head(20), use_container_width=True)

    if tamano_mb > LIMITE_MB:
        st.error(f"El archivo pesa {tamano_mb:.1f} MB. Lambda acepta hasta ~6 MB por request: divídelo en partes.")
        st.stop()

    if st.button("Predecir", type="primary"):
        with st.spinner("Enviando al modelo..."):
            try:
                st.session_state["resultado"] = predecir(API_URL, archivo.name, contenido)
            except requests.Timeout:
                st.error(f"La API no respondió en {TIMEOUT_S} s. Reintenta: si fue cold start, la segunda vez es rápida.")
            except requests.ConnectionError:
                st.error("No se pudo conectar con la API. Revisa API_URL y que el backend esté desplegado.")
            except RuntimeError as e:
                st.error(str(e))

resultado = st.session_state.get("resultado")
if resultado is not None:
    st.subheader("Predicciones")
    if COLUMNA_PREDICCION in resultado.columns:
        precios = resultado[COLUMNA_PREDICCION]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Casas", f"{len(resultado)}")
        c2.metric("Precio promedio", f"${precios.mean():,.0f}")
        c3.metric("Mínimo", f"${precios.min():,.0f}")
        c4.metric("Máximo", f"${precios.max():,.0f}")
        columnas = [COLUMNA_PREDICCION] + [c for c in resultado.columns if c != COLUMNA_PREDICCION]
        resultado = resultado[columnas]
        st.dataframe(
            resultado,
            use_container_width=True,
            column_config={COLUMNA_PREDICCION: st.column_config.NumberColumn("Precio estimado", format="$%.0f")},
        )
    else:
        st.dataframe(resultado, use_container_width=True)

    st.download_button(
        "Descargar CSV con predicciones",
        data=resultado.to_csv(index=False).encode("utf-8"),
        file_name="predicciones.csv",
        mime="text/csv",
    )
