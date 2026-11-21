"""API FastAPI que predice el precio de casas y corre en AWS Lambda vía Mangum."""

import io
import os
import traceback

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from mangum import Mangum

# 'configuraciones' e 'input' están al lado de main.py (raíz de /var/task en Lambda).
# 'input.preprocessors' además lo necesita el .joblib: el pipeline guarda clases de ese módulo.
from configuraciones import config
from input import preprocessors as pp  # noqa: F401

# Rutas relativas a este archivo (no a os.getcwd()), así funciona igual en Lambda y en local
DIRECTORIO_APP = os.path.dirname(os.path.abspath(__file__))
RUTA_MODELO = os.path.join(DIRECTORIO_APP, "precio_casas_pipeline.joblib")

# Tipos con los que los navegadores/clientes suelen enviar un CSV (Windows manda el de Excel)
TIPOS_CSV = {"text/csv", "application/csv", "application/vnd.ms-excel", "application/octet-stream"}

# BUENA PRÁCTICA LAMBDA: cargar el modelo UNA vez, en la fase de init (fuera del handler).
# Lambda reutiliza la instancia entre invocaciones "calientes", así que no se recarga por request.
PIPELINE = joblib.load(RUTA_MODELO)

app = FastAPI(title="API Precio de Casas")

# CORS: permite que un frontend web (React) en OTRO dominio llame a esta API desde el navegador.
# CORS_ORIGINS = lista separada por comas, p. ej. "http://localhost:5173,https://mi-app.vercel.app".
# Sin definir → "*" (cualquier origen; aceptable porque la API es pública y no usa cookies).
# No configures CORS también en la Function URL: los headers se duplicarían y el navegador falla.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Handler para AWS Lambda (la app no usa eventos de startup/shutdown → lifespan off)
handler = Mangum(app, lifespan="off")


def prediccion_o_inferencia(pipeline, datos):
    """Prepara los datos como en el entrenamiento y devuelve predicciones (log y escala real)."""
    datos = datos.drop(columns=["Id"], errors="ignore")

    columnas_faltantes = [c for c in config.FEATURES if c not in datos.columns]
    if columnas_faltantes:
        raise ValueError(f"Faltan columnas en el CSV: {columnas_faltantes}")

    datos = datos[config.FEATURES].copy()
    datos["MSSubClass"] = datos["MSSubClass"].astype("O")

    # Filas con nulos en variables que el pipeline NO sabe imputar → se descartan
    vars_imputables = (
        config.CATEGORICAL_VARS_WITH_NA_FREQUENT
        + config.CATEGORICAL_VARS_WITH_NA_MISSING
        + config.NUMERICAL_VARS_WITH_NA
    )
    nuevas_vars_con_na = [
        var for var in config.FEATURES
        if var not in vars_imputables and datos[var].isnull().sum() > 0
    ]
    datos = datos.dropna(subset=nuevas_vars_con_na).reset_index(drop=True)

    predicciones = pipeline.predict(datos)
    predicciones_sin_escalar = np.exp(predicciones)  # el modelo se entrenó con log(SalePrice)
    return predicciones, predicciones_sin_escalar, datos


@app.get("/")
def print_get():
    return {"mensaje": "API ML Funcionando - Docker - Kevin Inofuente"}


@app.post("/obtener-datos-de-usuario-y-predecir")
def publicar_mensaje(file: UploadFile = File(...)):
    es_csv = (file.filename or "").lower().endswith(".csv") or file.content_type in TIPOS_CSV
    if not es_csv:
        raise HTTPException(status_code=400, detail="El archivo debe ser un CSV")

    try:
        # Se lee en memoria: no se escribe en disco con el nombre que manda el usuario
        df_de_los_datos_subidos = pd.read_csv(file.file)
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo leer el CSV")

    try:
        predicciones, predicciones_sin_escalar, datos_procesados = prediccion_o_inferencia(
            PIPELINE, df_de_los_datos_subidos
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        traceback.print_exc()  # aparece en CloudWatch Logs
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")

    df_salida = datos_procesados.assign(
        Predicciones=predicciones,
        Predicciones_Sin_Escalar=predicciones_sin_escalar,
    )

    # Se devuelve el CSV desde memoria (sin pasar por /tmp)
    buffer = io.StringIO()
    df_salida.to_csv(buffer, index=False)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="salida_datos_y_predicciones.csv"'},
    )
