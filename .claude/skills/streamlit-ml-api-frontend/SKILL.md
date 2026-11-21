---
name: streamlit-ml-api-frontend
description: Frontend en Streamlit (Python) que consume por HTTP una API de predicción de ML — como el backend FastAPI de precio de casas desplegado en AWS Lambda con Function URL (POST multipart con un CSV, responde un CSV con predicciones). Vive en su propia carpeta hermana del backend, no importa su código, lee la URL del backend desde .env (API_URL), muestra el estado de la API, vista previa del CSV, métricas (promedio, mín, máx), tabla con el precio estimado y botón de descarga, y maneja cold start de Lambda, límite de 6 MB, timeouts y errores 400/422/500. Incluye plantilla probada (assets/app.py), ejecución local con uv y opciones de despliegue (Streamlit Community Cloud o Cloud Run). Use when the user asks for "un frontend en Streamlit para mi API", "consumir el backend de Lambda desde Streamlit", "interfaz para subir el CSV y ver las predicciones", "frontend en Python para el modelo", or types /streamlit-ml-api-frontend. Para un chat con un agente usa streamlit-agent-frontend; para un frontend web en JavaScript usa react-ml-api-frontend.
---

# Frontend en Streamlit para una API de predicción

Una interfaz en el navegador, escrita en Python, que **consume el backend por HTTP**. El frontend no importa `main.py` ni el modelo: solo conoce la URL y el contrato de la API. Así se enseña la arquitectura real (cliente ↔ servidor), y el mismo frontend funciona contra el backend local o contra Lambda cambiando una variable.

```
Navegador ──▶ app.py (Streamlit :8501, servidor Python) ──HTTP──▶ Backend FastAPI (Lambda / localhost:8000) ──▶ modelo
```

> **Streamlit vs React:** en Streamlit la llamada al backend la hace el **servidor Python**, no el navegador. Por eso **no necesita CORS**. Es la opción más rápida para un prototipo o una demo de data science. Si necesitas una web estática, publicable en Vercel o S3, usa `react-ml-api-frontend`.

Skill pensada para compartir con alumnos: no contiene datos de ninguna cuenta. La URL real del backend va en `.env`, y ese archivo no se sube a git.

## Contrato que espera del backend

| Ruta | Uso |
|---|---|
| `GET /` | Estado de la API. Responde JSON, idealmente con un campo `mensaje` |
| `POST /obtener-datos-de-usuario-y-predecir` | `multipart/form-data` con el campo **`file`** (CSV). Responde un **CSV** con las columnas de entrada + `Predicciones` + `Predicciones_Sin_Escalar` |
| Errores | JSON `{"detail": "..."}`: 400 (archivo inválido), 422 (faltan columnas), 500 (error interno) |

Si tu API usa otra ruta o columna, cambia `RUTA_PREDICCION` y `COLUMNA_PREDICCION` en `.env`; no hace falta tocar el código.

## Estructura

La carpeta del frontend va **al lado** del backend, no dentro:

```
repo/
├── .claude/skills/                       ← skills en la raíz
├── Backend-App-Problema-Regresion-Casas/  ← FastAPI + Dockerfile (Lambda)
└── Frontend-Streamlit-Problema-Regresion-Casas/
    ├── app.py              ← copia de assets/app.py
    ├── requirements.txt    ← copia de assets/requirements.txt
    ├── .env.example        ← copia de assets/.env.example (SÍ se sube)
    ├── .env                ← tu URL real (NO se sube)
    └── .gitignore          ← contenido de assets/gitignore.txt
```

## Paso 1 — Crear la carpeta desde las plantillas

Desde la raíz del repo (la skill vive en `~/.claude/skills/` o en `.claude/skills/` del repo):

```bash
SKILL=.claude/skills/streamlit-ml-api-frontend/assets    # o ~/.claude/skills/streamlit-ml-api-frontend/assets
FRONT=Frontend-Streamlit-Problema-Regresion-Casas

mkdir -p "$FRONT"
cp "$SKILL/app.py" "$SKILL/requirements.txt" "$SKILL/.env.example" "$FRONT/"
cp "$SKILL/gitignore.txt" "$FRONT/.gitignore"
cp "$FRONT/.env.example" "$FRONT/.env"
```

Adapta los textos de `app.py` (título, descripción, ícono) al problema. La lógica de llamada a la API no cambia.

## Paso 2 — Apuntar al backend

Edita `.env` (no se sube a git):

```bash
# Backend local
API_URL=http://localhost:8000
# Backend en Lambda: la Function URL, SIN "/" final
# API_URL=https://<id>.lambda-url.<region>.on.aws
```

Para obtener la Function URL del backend desplegado con `/aws-lambda-fastapi-deploy`:

```bash
aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --query FunctionUrl --output text
```

## Paso 3 — Ejecutar en local

```bash
cd "$FRONT"
uv venv --python 3.11 .venv          # skill /uv-create-venv si no tienes uv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
streamlit run app.py                 # http://localhost:8501
```

Para probar contra el **backend local** sin desplegar, levanta la API desde la carpeta del backend. Usa la misma imagen que va a Lambda, con uvicorn instalado al vuelo:

```bash
cd Backend-App-Problema-Regresion-Casas
docker build --platform linux/amd64 --provenance=false -t api-local .
docker run --rm -p 8000:8000 --entrypoint /bin/sh api-local -c \
  "pip install -q uvicorn --target /tmp/uv && PYTHONPATH=/tmp/uv:/var/task python -m uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir /var/task"
```

## Qué hace la plantilla (`assets/app.py`)

| Parte | Detalle |
|---|---|
| Barra lateral | URL del backend, estado de `GET /` cacheado 30 s y botón "Volver a comprobar" |
| Subida | `st.file_uploader` solo para `.csv`, con vista previa (20 filas), filas, columnas y MB |
| Límite de Lambda | Si el CSV pesa más de ~5.5 MB, avisa y no lo envía (Lambda acepta 6 MB por request) |
| Llamada | `requests.post(..., files={"file": (nombre, bytes, "text/csv")}, timeout=90)`; el timeout amplio cubre el cold start |
| Errores | Timeout, conexión y HTTP 4xx/5xx se muestran con el `detail` de FastAPI |
| Resultado | Métricas (casas, promedio, mín, máx), tabla con la columna de precio primero en formato `$` y botón de descarga |
| Estado | El resultado se guarda en `st.session_state` para que no se pierda en cada rerun |

Buenas prácticas aplicadas:
- **Configuración por entorno:** `API_URL` en `.env`, nunca en el código.
- **`requests` con `timeout`:** sin timeout, la app queda colgada si la API no responde.
- **Errores legibles para el usuario:** nada de tracebacks en pantalla.
- **Formulario `multipart` con campo `file`:** el nombre del campo debe coincidir con el parámetro `file: UploadFile` de FastAPI.

## Paso 4 — Desplegar (opcional)

| Opción | Cuándo | Cómo |
|---|---|---|
| **Streamlit Community Cloud** | Demo gratis y rápida | Sube el repo a GitHub → share.streamlit.io → *New app* → *Main file path*: `Frontend-.../app.py`. En *Advanced settings → Secrets* pon `API_URL = "https://..."` |
| **Google Cloud Run** | Contenedor propio, escala a cero | Skill `/gcp-cloud-run-deploy`, con `API_URL` como variable de entorno del servicio |

En Streamlit Cloud los *Secrets* se exponen como variables de entorno, así que `os.getenv("API_URL")` funciona sin cambios.

## Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| "No se pudo conectar con la API" | `API_URL` mal escrita, backend apagado o borrado | Prueba `curl $API_URL/` y revisa `.env` |
| `Error 403: Forbidden` | Faltan los permisos públicos de la Function URL | Paso 6 de `/aws-lambda-fastapi-deploy` |
| La primera predicción tarda o da timeout | Cold start de Lambda | Reintenta; si pasa siempre, sube la memoria de la Lambda |
| `Error 422: Faltan columnas...` | El CSV no tiene las columnas que espera el modelo | Usa el CSV de ejemplo del backend como guía |
| `Error 400: El archivo debe ser un CSV` | Extensión o content-type incorrectos | La plantilla ya envía `text/csv`; revisa la extensión |
| `Error 500` | Fallo dentro del backend | `aws logs tail /aws/lambda/$FUNCTION_NAME` |
| `URL//obtener...` (doble barra) | `API_URL` termina en `/` | La plantilla hace `rstrip("/")`; si cambiaste el código, quítala |
| `ModuleNotFoundError: dotenv` | Falta instalar los requirements | `uv pip install -r requirements.txt` |
