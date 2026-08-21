from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
import os
import pandas as pd
import numpy as np
import joblib
import subprocess
from mangum import Mangum

# --- CORRECCIÓN 1: IMPORTS ---
# Tus carpetas 'configuraciones' e 'input' están al lado de main.py,
# NO dentro de una carpeta 'src'.
try:
    from configuraciones import config
    from input import preprocessors as pp
except ImportError:
    # Fallback por si acaso en local sí usas src (pero en Docker no deberías)
    from src.configuraciones import config
    from src.input import preprocessors as pp

# from Scikit-learn
from sklearn.linear_model import Lasso
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler, Binarizer

# from feature-engine
from feature_engine.imputation import (
    AddMissingIndicator,
    MeanMedianImputer,
    CategoricalImputer,
)
from feature_engine.encoding import (
    RareLabelEncoder,
    OrdinalEncoder,
)
from feature_engine.transformation import LogTransformer
from feature_engine.selection import DropFeatures
from feature_engine.wrappers import SklearnTransformerWrapper

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

@app.get("/rutas")
def debug_rutas():
    # Endpoint útil para ver qué archivos ve realmente Python
    files = os.listdir(ruta_actual)
    return {"ruta_actual": ruta_actual, "archivos_en_raiz": files}

@app.post("/obtener-datos-de-usuario-y-predecir")
def publicar_mensaje(file: UploadFile = File(...)):

    if file.content_type != 'text/csv':
        raise HTTPException(status_code=400, detail="El archivo debe ser un CSV")
    
    try:
        # --- CORRECCIÓN 2: Escribir en /tmp ---
        file_location = f"{ruta_temporal}/{file.filename}"
        
        with open(file_location, "wb") as buffer:
            buffer.write(file.file.read())

        # Leer el archivo CSV
        df_de_los_datos_subidos = pd.read_csv(file_location)

        # --- CORRECCIÓN 3: Cargar Modelo ---
        # Buscamos el modelo en la raíz (donde lo puso Docker)
        nombre_modelo = "precio_casas_pipeline.joblib"
        ruta_modelo = os.path.join(ruta_actual, nombre_modelo)
        
        if not os.path.exists(ruta_modelo):
            # Intento secundario por si acaso
            ruta_modelo = os.path.join(ruta_actual, "src", nombre_modelo)

        if not os.path.exists(ruta_modelo):
            raise FileNotFoundError(f"NO ENCUENTRO EL MODELO EN: {ruta_modelo}. Archivos visibles: {os.listdir(ruta_actual)}")

        pipeline_de_produccion = joblib.load(ruta_modelo)

        # Hacer la predicción
        predicciones, predicciones_sin_escalar, datos_test_procesados = prediccion_o_inferencia(pipeline_de_produccion, df_de_los_datos_subidos)

        # Concatenar
        df_concatenado = pd.concat([datos_test_procesados, pd.Series(predicciones, name="Predicciones"), pd.Series(predicciones_sin_escalar, name="Predicciones_Sin_Escalar")], axis=1)

        # --- CORRECCIÓN 4: Guardar salida en /tmp ---
        output_file = f"{ruta_temporal}/salida_datos_y_predicciones.csv"
        df_concatenado.to_csv(output_file, index=False)

        # Devolver el archivo
        return FileResponse(output_file, media_type="application/octet-stream", filename="salida_datos_y_predicciones.csv")

    except Exception as e:
        # Esto imprime el error real en los logs de AWS CloudWatch
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")