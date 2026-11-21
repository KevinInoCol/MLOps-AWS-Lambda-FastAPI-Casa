from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
import os
import traceback
import pandas as pd
import numpy as np
import joblib
from mangum import Mangum

# 'configuraciones' e 'input' están al lado de main.py (raíz de /var/task en Lambda).
# 'input.preprocessors' además lo necesita el .joblib: el pipeline guarda clases de ese módulo.
from configuraciones import config
from input import preprocessors as pp  # noqa: F401

app = FastAPI()

# Handler para AWS Lambda
handler = Mangum(app)

# Ruta actual (En Lambda es /var/task -> SOLO LECTURA)
ruta_actual = os.getcwd()
# Ruta temporal (En Lambda es /tmp -> LECTURA Y ESCRITURA)
ruta_temporal = "/tmp"

def prediccion_o_inferencia(pipeline_de_test, datos_de_test):
    # Dropeamos
    if 'Id' in datos_de_test.columns:
        datos_de_test.drop('Id', axis=1, inplace=True)

    # Cast MSSubClass as object
    if 'MSSubClass' in datos_de_test.columns:
        datos_de_test['MSSubClass'] = datos_de_test['MSSubClass'].astype('O')

    datos_de_test = datos_de_test[config.FEATURES]

    new_vars_with_na = [
        var for var in config.FEATURES
        if var not in config.CATEGORICAL_VARS_WITH_NA_FREQUENT +
        config.CATEGORICAL_VARS_WITH_NA_MISSING +
        config.NUMERICAL_VARS_WITH_NA
        and datos_de_test[var].isnull().sum() > 0]

    datos_de_test.dropna(subset=new_vars_with_na, inplace=True)

    # Inferencia
    predicciones = pipeline_de_test.predict(datos_de_test)
    # Desescalando
    predicciones_sin_escalar = np.exp(predicciones)
    return predicciones, predicciones_sin_escalar, datos_de_test

@app.get("/")
def print_get():
    return {"mensaje": "API ML Funcionando - Docker - Kevin Inofuente"}

@app.post("/obtener-datos-de-usuario-y-predecir")
def publicar_mensaje(file: UploadFile = File(...)):

    if file.content_type != 'text/csv':
        raise HTTPException(status_code=400, detail="El archivo debe ser un CSV")

    try:
        # Escribir en /tmp (única ruta escribible en Lambda)
        file_location = f"{ruta_temporal}/{file.filename}"

        with open(file_location, "wb") as buffer:
            buffer.write(file.file.read())

        # Leer el archivo CSV
        df_de_los_datos_subidos = pd.read_csv(file_location)

        # Cargar el modelo desde la raíz (donde lo puso Docker)
        nombre_modelo = "precio_casas_pipeline.joblib"
        ruta_modelo = os.path.join(ruta_actual, nombre_modelo)

        if not os.path.exists(ruta_modelo):
            raise FileNotFoundError(f"NO ENCUENTRO EL MODELO EN: {ruta_modelo}")

        pipeline_de_produccion = joblib.load(ruta_modelo)

        # Hacer la predicción
        predicciones, predicciones_sin_escalar, datos_test_procesados = prediccion_o_inferencia(pipeline_de_produccion, df_de_los_datos_subidos)

        # Concatenar
        df_concatenado = pd.concat([datos_test_procesados, pd.Series(predicciones, name="Predicciones"), pd.Series(predicciones_sin_escalar, name="Predicciones_Sin_Escalar")], axis=1)

        # Guardar salida en /tmp
        output_file = f"{ruta_temporal}/salida_datos_y_predicciones.csv"
        df_concatenado.to_csv(output_file, index=False)

        # Devolver el archivo
        return FileResponse(output_file, media_type="application/octet-stream", filename="salida_datos_y_predicciones.csv")

    except Exception as e:
        # Esto imprime el error real en los logs de AWS CloudWatch
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")
