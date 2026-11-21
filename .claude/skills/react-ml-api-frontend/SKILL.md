---
name: react-ml-api-frontend
description: Frontend web en React + Vite (JavaScript) que consume por HTTP una API de predicción de ML — como el backend FastAPI de precio de casas desplegado en AWS Lambda con Function URL (POST multipart con un CSV, responde un CSV con predicciones). Vive en su propia carpeta hermana del backend, lee la URL desde VITE_API_URL, muestra el estado de la API, vista previa del CSV, métricas (promedio, mín, máx), tabla con el precio estimado y descarga, maneja cold start, límite de 6 MB, timeouts, CORS y errores 400/422/500, con tema claro/oscuro y diseño responsive. Incluye plantillas probadas (assets/src: api.js, App.jsx, App.css), el CORSMiddleware que necesita el backend y despliegue estático en Vercel. Use when the user asks for "un frontend en React para mi API", "consumir el backend de Lambda desde React", "frontend web para el modelo", "app en Vite que suba el CSV", "error de CORS al llamar a mi API", or types /react-ml-api-frontend. Para un frontend en Python usa streamlit-ml-api-frontend.
---

# Frontend en React (Vite) para una API de predicción

Una web estática (HTML + JS) que **el navegador del usuario** ejecuta y que llama al backend por HTTP. No hay servidor propio: se publica como archivos estáticos (Vercel, S3, Netlify).

```
Navegador (React, JS) ──HTTP + CORS──▶ Backend FastAPI (Lambda Function URL / localhost:8000) ──▶ modelo
```

> **Diferencia clave con Streamlit:** aquí la llamada sale **del navegador**, desde otro dominio (`localhost:5173`, `mi-app.vercel.app`). El navegador la bloquea si el backend no responde con headers **CORS**. Por eso el Paso 1 se hace en el backend.

Skill pensada para compartir con alumnos: no contiene datos de ninguna cuenta. La URL real va en `.env`, y ese archivo no se sube a git.

## Contrato que espera del backend

| Ruta | Uso |
|---|---|
| `GET /` | Estado de la API. Responde JSON, idealmente con un campo `mensaje` |
| `POST /obtener-datos-de-usuario-y-predecir` | `multipart/form-data` con el campo **`file`** (CSV). Responde un **CSV** con las columnas de entrada + `Predicciones` + `Predicciones_Sin_Escalar` |
| Errores | JSON `{"detail": "..."}`: 400, 422 (faltan columnas), 500 |

Si tu API usa otra ruta o columna, cambia `VITE_RUTA_PREDICCION` y `VITE_COLUMNA_PREDICCION` en `.env`.

## Paso 1 — Habilitar CORS en el backend (una sola vez)

En `main.py` del backend, justo después de `app = FastAPI(...)`:

```python
from fastapi.middleware.cors import CORSMiddleware

# CORS_ORIGINS = lista separada por comas, p. ej. "http://localhost:5173,https://mi-app.vercel.app"
# Sin definir → "*" (aceptable si la API es pública y no usa cookies)
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

Vuelve a desplegar la imagen (Paso 8 de `/aws-lambda-fastapi-deploy`). Para restringir los orígenes en Lambda, usa la sintaxis JSON, porque las comas rompen la sintaxis corta:

```bash
aws lambda update-function-configuration --function-name "$FUNCTION_NAME" \
  --environment '{"Variables":{"CORS_ORIGINS":"http://localhost:5173,https://mi-app.vercel.app"}}'
```

> **CORS solo en un lugar.** Si lo activas en FastAPI, **no** configures también `--cors` en la Function URL. Los headers `Access-Control-Allow-Origin` se duplican y el navegador rechaza la respuesta.

Comprobar sin navegador:

```bash
curl -s -i -X OPTIONS "$API_URL/obtener-datos-de-usuario-y-predecir" \
  -H "Origin: http://localhost:5173" -H "Access-Control-Request-Method: POST" | grep -i access-control-allow-origin
```

## Paso 2 — Crear el proyecto con Vite

Desde la raíz del repo (requiere Node 20 o superior):

```bash
FRONT=Frontend-React-Problema-Regresion-Casas
SKILL=.claude/skills/react-ml-api-frontend/assets    # o ~/.claude/skills/react-ml-api-frontend/assets

npm create vite@latest "$FRONT" -- --template react --no-interactive
cd "$FRONT"
npm install
npm install papaparse                       # parser de CSV robusto (comillas, comas, tipos)

# Plantillas de la skill
cp "$SKILL/src/api.js" "$SKILL/src/App.jsx" "$SKILL/src/App.css" src/
rm -f src/index.css && sed -i.bak '/index.css/d' src/main.jsx && rm -f src/main.jsx.bak
cp "$SKILL/env.example" .env.example
cp .env.example .env
grep -qxF '.env' .gitignore || echo '.env' >> .gitignore
```

Resultado:

```
Frontend-React-Problema-Regresion-Casas/
├── src/
│   ├── api.js      ← única capa que habla con el backend (URL, timeout, errores)
│   ├── App.jsx     ← interfaz
│   ├── App.css     ← estilos (claro/oscuro, responsive)
│   └── main.jsx    ← generado por Vite
├── .env.example    ← SÍ se sube
├── .env            ← tu URL real (NO se sube)
└── package.json
```

Adapta título y textos en `App.jsx`. La lógica de red vive solo en `api.js`.

## Paso 3 — Apuntar al backend y ejecutar

`.env`:

```bash
VITE_API_URL=http://localhost:8000
# VITE_API_URL=https://<id>.lambda-url.<region>.on.aws     ← Function URL, SIN "/" final
```

```bash
npm run dev          # http://localhost:5173 (recarga en caliente)
npm run build        # genera dist/ (archivos estáticos para publicar)
npm run preview      # sirve dist/ en http://localhost:4173
```

> Las variables `VITE_*` se **incrustan en el JavaScript al compilar**. Si cambias `.env`, reinicia `npm run dev` o vuelve a hacer `build`. Y **nunca** pongas secretos en `VITE_*`: cualquiera los ve con "Ver código fuente". La URL de una API pública no es un secreto.

Backend local para probar sin desplegar: el comando `docker run ... uvicorn` de la skill `streamlit-ml-api-frontend`, Paso 3. Si restringes orígenes, añade `-e CORS_ORIGINS=http://localhost:5173`.

## Qué hacen las plantillas

| Archivo | Responsabilidad |
|---|---|
| `api.js` | Lee `VITE_API_URL` y quita la `/` final. `fetch` con timeout de 90 s (`AbortController`) para el cold start. `FormData` con el campo `file`, **sin** poner `Content-Type` a mano (el navegador agrega el boundary). Traduce errores de red, timeout y `detail` de FastAPI a mensajes legibles |
| `App.jsx` | Chip de estado de la API con reintento. Selector de CSV con vista previa (papaparse). Aviso de más de 5.5 MB. Botón Predecir con estado "Prediciendo…". Métricas, tabla con el precio en `$` primero (50 filas) y descarga del CSV completo |
| `App.css` | Variables CSS, tema claro/oscuro con `prefers-color-scheme`, tabla con scroll horizontal y diseño que funciona en móvil |

Buenas prácticas aplicadas:
- **Una sola capa de red (`api.js`):** los componentes no conocen URLs ni `fetch`.
- **Configuración por entorno:** cambiar de local a Lambda no toca código.
- **Estados de carga y error visibles:** botón deshabilitado mientras se envía y mensajes de error que dicen qué hacer.
- **Validar en el cliente antes de enviar:** extensión `.csv` y tamaño. El backend vuelve a validar igual.
- **No renderizar miles de filas:** la tabla muestra 50 y la descarga trae todo.

## Paso 4 — Publicar en Vercel

Usa la skill `/vercel-frontend-deploy`. Puntos clave:
- **Root Directory:** `Frontend-React-Problema-Regresion-Casas`. Framework: Vite. Output: `dist`.
- **Environment Variables:** `VITE_API_URL=https://<id>.lambda-url.<region>.on.aws`. Hay que definirla **antes** del build: si la cambias, vuelve a desplegar.
- Después, añade el dominio de Vercel a `CORS_ORIGINS` del backend (Paso 1), o deja `*`.

Alternativa en AWS: `npm run build` y luego subir `dist/` a un bucket S3 con CloudFront, o usar AWS Amplify Hosting.

## Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| Consola: `blocked by CORS policy: No 'Access-Control-Allow-Origin'` | El backend no tiene CORS o no incluye tu origen | Paso 1 y vuelve a desplegar la Lambda |
| Consola: `The 'Access-Control-Allow-Origin' header contains multiple values` | CORS configurado en FastAPI **y** en la Function URL | Quita el de la Function URL: `aws lambda update-function-url-config --function-name ... --cors '{}'` |
| "No se pudo conectar con la API" | Backend caído, URL mal escrita o CORS | Abre `VITE_API_URL` en el navegador; si responde, es CORS |
| Sigue llamando a la URL vieja | `VITE_*` se incrusta al compilar | Reinicia `npm run dev` o haz un nuevo build y despliegue |
| `Error 403` | Permisos públicos de la Function URL | Paso 6 de `/aws-lambda-fastapi-deploy` |
| `Error 422: Faltan columnas` | CSV con columnas incorrectas | Usa el CSV de ejemplo del backend |
| `Error 400` con multipart | Pusiste `Content-Type` a mano en `fetch` | Deja que el navegador lo ponga (la plantilla ya lo hace) |
| Mixed content (`https` → `http`) | Frontend publicado en https llamando a `http://localhost` | En producción usa la Function URL (https) |
| Timeout en la primera llamada | Cold start de Lambda | Reintenta; sube la memoria de la Lambda si pasa siempre |
