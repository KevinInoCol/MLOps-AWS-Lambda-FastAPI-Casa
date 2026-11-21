---
name: aws-lambda-fastapi-deploy
description: Despliega una API FastAPI (p. ej. un modelo de ML con scikit-learn/pandas servido por un pipeline .joblib) en AWS Lambda como IMAGEN DE CONTENEDOR — Dockerfile sobre la imagen base oficial de Lambda, Mangum como handler, push a un repositorio privado de Amazon ECR y función creada con --package-type Image — y la expone con una Function URL pública. Cubre prerequisitos (AWS CLI v2, Docker, Python 3.11), rol IAM de ejecución, build para linux/amd64 con --provenance=false (Mac Apple Silicon), prueba local con el emulador de Lambda, /tmp como única ruta escribible, pruebas con curl (GET y subida de CSV multipart), actualización de la imagen, logs en CloudWatch, limpieza completa (Lambda + ECR + rol) y solución de problemas. Incluye un anexo con el método alternativo por ZIP. Use when the user asks to "desplegar en Lambda", "subir mi FastAPI a AWS Lambda", "Lambda con contenedor", "subir la imagen a ECR", "Mangum", "Function URL", "el handler de Lambda no encuentra el módulo", "borrar la Lambda", or types /aws-lambda-fastapi-deploy.
---

# FastAPI en AWS Lambda con contenedor (ECR)

Skill pensada para clase: se comparte con alumnos, así que **no contiene datos de ninguna cuenta**. Todo lo específico (cuenta, región, nombres) va en variables de shell que cada quien define.

> **Reglas de seguridad (no negociables)**
> - Nunca escribas Access Keys, Secret Keys, IDs de cuenta ni contraseñas en archivos del proyecto, en el `Dockerfile`, en el código ni en esta skill. Las credenciales viven solo en `~/.aws/` (vía `aws configure` o `aws configure sso`).
> - El ID de cuenta se obtiene en tiempo de ejecución con `aws sts get-caller-identity`; no se copia a mano.
> - No uses el usuario root de AWS: crea un usuario IAM (o SSO) para la clase.
> - `.env` y `.aws/` van en `.gitignore` **y** en `.dockerignore`, para que no terminen dentro de la imagen.
> - Una Function URL con `auth-type NONE` es **pública**: cualquiera con la URL puede invocarla. Bórrala al terminar la clase (Paso 9).

## Cómo encaja todo

```
Dockerfile + application/ ──docker build──▶ imagen local ──docker push──▶ ECR (repo privado)
                                                                              │
                                              Lambda (--package-type Image) ◀─┘
                                                     │
                                       Function URL pública ──▶ curl / navegador (/docs)
```

Lambda **solo** acepta imágenes de un repositorio **privado de ECR en la misma región** que la función. No acepta Docker Hub ni ECR Public. La imagen base `public.ecr.aws/lambda/python:3.11` se usa solo en el `FROM` para construir.

## Estructura esperada del proyecto

```
proyecto/
├── application/                  # su CONTENIDO va a /var/task (raíz de la Lambda)
│   ├── main.py                   # app = FastAPI(); handler = Mangum(app)
│   ├── modelo.joblib             # artefacto del modelo
│   ├── configuraciones/          # paquetes importados por main.py
│   └── input/                    # transformadores propios usados por el pipeline
├── requirements.txt              # incluye mangum y python-multipart
├── Dockerfile
└── .dockerignore
```

Requisitos en el código (`main.py`):

```python
from fastapi import FastAPI
from mangum import Mangum

app = FastAPI()
handler = Mangum(app)            # el Dockerfile termina con CMD ["main.handler"]
```

- `/var/task` (donde vive el código) es **solo lectura**. Cualquier archivo temporal (CSV subidos, salidas) se escribe en **`/tmp`** (512 MB por defecto, ampliable hasta 10 GB con `--ephemeral-storage`).
- Los imports son relativos a la raíz de `application/` (`from configuraciones import config`), porque su contenido queda en la raíz de `/var/task`.
- Si el pipeline usa transformadores propios (clases en `input/preprocessors.py`), el `.joblib` guarda la ruta del módulo (p. ej. `input.preprocessors`). **Esa carpeta debe existir con el mismo nombre en la imagen**, o `joblib.load` falla con `ModuleNotFoundError`.
- Fija versiones de las librerías que serializan el modelo (`scikit-learn`, `feature-engine`, `numpy`) **iguales a las del entrenamiento**, o `joblib.load` fallará o predecirá distinto.
- Para subir archivos con `UploadFile` hace falta `python-multipart` en `requirements.txt`.

## Paso 0 — Prerequisitos y variables

```bash
aws --version                      # AWS CLI v2 (si falta: skill /install-aws-cli)
aws sts get-caller-identity        # confirma que hay sesión y que NO es root
docker --version                   # Docker Desktop abierto y corriendo
docker info >/dev/null && echo "Docker OK"
```

Si `aws sts get-caller-identity` falla, configura la sesión con `aws configure`. Las llaves se escriben **solo en la terminal**, nunca en un archivo del proyecto.

Define las variables (ajusta los valores a tu gusto; no son secretos):

```bash
export AWS_REGION=us-east-1
export FUNCTION_NAME=api-fastapi-modelo
export ROLE_NAME=${FUNCTION_NAME}-role
export ECR_REPO=${FUNCTION_NAME}
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR_REGISTRY=${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com
export IMAGE_URI=${ECR_REGISTRY}/${ECR_REPO}:latest
```

Las variables se pierden al cerrar la terminal. Si abres otra, vuelve a ejecutar este bloque.

## Paso 1 — Dockerfile y .dockerignore

`Dockerfile` (imagen base oficial de Lambda):

```dockerfile
FROM public.ecr.aws/lambda/python:3.11

COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Wheels de Linux x86_64 y sin compilar desde fuente (evita "gcc not found")
RUN pip install --upgrade pip && \
    pip install -r requirements.txt --only-binary=:all: \
      --platform manylinux2014_x86_64 --target "${LAMBDA_TASK_ROOT}"

# El CONTENIDO de application/ va a la raíz de /var/task
COPY application/ ${LAMBDA_TASK_ROOT}

CMD [ "main.handler" ]
```

`.dockerignore` (mínimo):

```
.env
.aws/
.git/
.venv/
venv/
__pycache__/
*.pyc
dependencies/
*.zip
*.md
.vscode/
.DS_Store
```

## Paso 2 — Rol IAM de ejecución

```bash
cat > /tmp/trust-lambda.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "lambda.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role --role-name "$ROLE_NAME" \
  --assume-role-policy-document file:///tmp/trust-lambda.json

aws iam attach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

export ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)
```

`AWSLambdaBasicExecutionRole` solo permite escribir logs en CloudWatch. Si la app lee de S3 u otro servicio, añade una política **mínima** para ese recurso, no `AdministratorAccess`.

## Paso 3 — Crear el repositorio en ECR

```bash
aws ecr create-repository --repository-name "$ECR_REPO" \
  --image-scanning-configuration scanOnPush=true --region "$AWS_REGION"
```

Es lo mismo que **ECR → Create repository** en la consola (visibilidad: *Private*).

## Paso 4 — Build, prueba local y push

```bash
# 1. Login de Docker contra ECR (el token va por pipe y caduca en 12 h; no se guarda en archivos)
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ECR_REGISTRY"

# 2. Build para x86_64 y SIN attestations (Lambda no acepta el manifest index de buildx)
docker build --platform linux/amd64 --provenance=false -t "$ECR_REPO" .
```

> En Mac con Apple Silicon (M1/M2/M3/M4), `--platform linux/amd64` es obligatorio. Sin él la imagen sale arm64 y la Lambda x86_64 falla con `exec format error`.
> Los "View push commands" de la consola de ECR **no** incluyen `--platform` ni `--provenance=false`; por eso se reemplaza su comando de build por este.

Prueba local opcional antes de subir (la imagen base trae el emulador de Lambda):

```bash
docker run --rm -p 9000:8080 "$ECR_REPO"
# en otra terminal, un evento HTTP mínimo (formato Function URL / API Gateway v2):
curl -s -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"version":"2.0","rawPath":"/","requestContext":{"http":{"method":"GET","path":"/","sourceIp":"127.0.0.1"}},"headers":{},"isBase64Encoded":false}'
# debe responder {"statusCode": 200, ... "body": "{\"mensaje\": ...}"}
```

```bash
# 3. Tag + push a ECR
docker tag "$ECR_REPO:latest" "$IMAGE_URI"
docker push "$IMAGE_URI"

aws ecr describe-images --repository-name "$ECR_REPO" --region "$AWS_REGION" \
  --query 'imageDetails[].{tags:imageTags,MB:imageSizeInBytes}'
```

## Paso 5 — Crear la Lambda desde la imagen

```bash
aws lambda create-function --function-name "$FUNCTION_NAME" \
  --package-type Image --code ImageUri="$IMAGE_URI" \
  --architectures x86_64 --role "$ROLE_ARN" \
  --memory-size 2048 --timeout 60 --region "$AWS_REGION"

aws lambda wait function-active-v2 --function-name "$FUNCTION_NAME" --region "$AWS_REGION"
aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --region "$AWS_REGION" \
  --query '{Estado:State,Ultima:LastUpdateStatus,Memoria:MemorySize,Timeout:Timeout}'
```

- Si responde `The role defined for the function cannot be assumed`, el rol aún no se propagó: espera 10 a 20 s y repite.
- En consola: **Lambda → Create function → Container image → Browse images** (elige el repo y la etiqueta `latest`). En *Permissions*, usa el rol existente.
- 2048 MB y 60 s son un buen punto de partida para pandas + scikit-learn. Más memoria también da más CPU.

## Paso 6 — Exponer con una Function URL pública

```bash
aws lambda create-function-url-config --function-name "$FUNCTION_NAME" \
  --auth-type NONE --region "$AWS_REGION"

# Permiso público para invocar por la URL
aws lambda add-permission --function-name "$FUNCTION_NAME" \
  --statement-id url-publica --action lambda:InvokeFunctionUrl \
  --principal "*" --function-url-auth-type NONE --region "$AWS_REGION"

# En cuentas/regiones con la política nueva también hace falta lambda:InvokeFunction vía URL.
# Si la URL responde 403 Forbidden, añade este segundo permiso:
aws lambda add-permission --function-name "$FUNCTION_NAME" \
  --statement-id url-publica-invoke --action lambda:InvokeFunction \
  --principal "*" --invoked-via-function-url --region "$AWS_REGION"

export FUNCTION_URL=$(aws lambda get-function-url-config --function-name "$FUNCTION_NAME" \
  --region "$AWS_REGION" --query FunctionUrl --output text)
echo "$FUNCTION_URL"
```

En consola: **Configuration → Function URL → Create function URL → Auth type: NONE**.

Alternativa: API Gateway HTTP API. Es más configurable (dominio propio, throttling), pero para clase la Function URL basta.

## Paso 7 — Probar

```bash
curl -s "${FUNCTION_URL}"                                        # GET /  → mensaje de bienvenida
curl -s "${FUNCTION_URL}docs" -o /dev/null -w '%{http_code}\n'   # Swagger UI → 200

# Subir un CSV y recibir el CSV con predicciones (ajusta la ruta del endpoint)
curl -s -X POST "${FUNCTION_URL}obtener-datos-de-usuario-y-predecir" \
  -F "file=@datos_prueba.csv;type=text/csv" \
  -o salida_predicciones.csv
head salida_predicciones.csv
```

También se prueba en el navegador abriendo `${FUNCTION_URL}docs` → *Try it out*.

- La primera llamada tarda más por el **cold start**: Lambda descarga la imagen e importa pandas y scikit-learn. Puede llevar 5 a 15 s.
- Límite de **6 MB** por request y por response en invocación síncrona. Para CSV grandes, sube el archivo a S3 y pasa la ruta.

## Paso 8 — Actualizar tras cambiar el código o el modelo

```bash
docker build --platform linux/amd64 --provenance=false -t "$ECR_REPO" .
docker tag "$ECR_REPO:latest" "$IMAGE_URI"
docker push "$IMAGE_URI"

aws lambda update-function-code --function-name "$FUNCTION_NAME" \
  --image-uri "$IMAGE_URI" --region "$AWS_REGION"
aws lambda wait function-updated-v2 --function-name "$FUNCTION_NAME" --region "$AWS_REGION"
```

El `push` por sí solo **no** actualiza la Lambda: hace falta `update-function-code`, porque Lambda fija el digest de la imagen al crearla o actualizarla.

Logs en vivo (los `print` y `traceback.print_exc()` de la app aparecen aquí):

```bash
aws logs tail "/aws/lambda/$FUNCTION_NAME" --follow --region "$AWS_REGION"
```

Cada invocación termina con `REPORT ... Max Memory Used`, útil para ajustar la memoria.

## Paso 9 — Limpieza (al terminar la clase)

```bash
aws lambda delete-function-url-config --function-name "$FUNCTION_NAME" --region "$AWS_REGION"
aws lambda delete-function --function-name "$FUNCTION_NAME" --region "$AWS_REGION"
aws logs delete-log-group --log-group-name "/aws/lambda/$FUNCTION_NAME" --region "$AWS_REGION"

aws ecr delete-repository --repository-name "$ECR_REPO" --force --region "$AWS_REGION"

aws iam detach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name "$ROLE_NAME"

docker rmi "$IMAGE_URI" "$ECR_REPO:latest" 2>/dev/null; docker image prune -f
```

Costo: Lambda cobra por invocación y por GB-segundo (hay capa gratuita), así que una función sin tráfico casi no cuesta. Lo que sí cobra en reposo es el almacenamiento de la imagen en ECR (por GB-mes), y la URL pública queda expuesta. Por eso se limpia.

## Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop cerrado | Ábrelo y repite |
| `no basic auth credentials` / `denied` en el push | No hiciste login a ECR, caducó (12 h) o la región no coincide | Repite el login del Paso 4 con la misma `AWS_REGION` |
| `name unknown: The repository ... does not exist` | No creaste el repo o lo creaste en otra región | Paso 3 en la región correcta |
| `The image manifest, config or layer media type ... is not supported` | buildx subió un manifest index con attestations | `docker build --provenance=false` y vuelve a hacer push |
| `exec format error` / `Runtime.InvalidEntrypoint` | Imagen arm64 en una Lambda x86_64 | `--platform linux/amd64` |
| `Source image ... is not valid` / `does not exist` | `IMAGE_URI` mal formada, tag inexistente o repo en otra región | `aws ecr describe-images` y revisa la URI |
| `gcc: command not found` durante el build | pip intenta compilar desde fuente | `--only-binary=:all:` y versiones con wheel para Python 3.11 |
| `Runtime.ImportModuleError: No module named 'main'` | `main.py` no quedó en la raíz de `/var/task` | `COPY application/ ${LAMBDA_TASK_ROOT}` (copia el contenido, no la carpeta) |
| `ModuleNotFoundError: No module named 'input'` al cargar el modelo | Falta la carpeta de transformadores propios que referencia el `.joblib` | Cópiala con el mismo nombre de módulo |
| `Read-only file system` | La app escribe en `/var/task` | Escribe en `/tmp` |
| `Task timed out after 3.00 seconds` | Timeout por defecto | `--timeout 60` o más (máximo 900) |
| `Runtime exited with error: signal: killed` | Memoria insuficiente | Sube `--memory-size` |
| `403 Forbidden` / `{"Message":"Forbidden"}` en la URL | Faltan permisos de la Function URL | Los dos `add-permission` del Paso 6 |
| La Lambda sigue con el código viejo | Hiciste push pero no actualizaste la función | `update-function-code` (Paso 8) |
| Warning `InconsistentVersionWarning` de sklearn o predicciones raras | Versión de scikit-learn distinta a la del entrenamiento | Fija la misma versión en `requirements.txt` |
| `400 El archivo debe ser un CSV` | curl no envió `content-type` | `-F "file=@archivo.csv;type=text/csv"` |

---

## Anexo — Método alternativo por ZIP (sin Docker)

Úsalo solo si no puedes instalar Docker. Límites: **50 MB** de zip en subida directa (si pesa más, súbelo por S3) y **250 MB descomprimido**. Con pandas, scikit-learn y scipy suele quedar justo o pasarse; si es así, usa el contenedor. Necesita los Pasos 0 y 2; los demás pasos de ECR no aplican.

```bash
rm -rf dependencies aws_lambda_artifact.zip

# Dependencias como binarios de Linux x86_64 para Python 3.11
pip3 install -t dependencies -r requirements.txt \
  --platform manylinux2014_x86_64 --implementation cp \
  --python-version 3.11 --only-binary=:all: --upgrade
du -sh dependencies          # si pasa de ~240 MB → usa el contenedor

# Dependencias + código en la RAÍZ del zip (sin carpeta application/ dentro)
(cd dependencies && zip -qr ../aws_lambda_artifact.zip .)
(cd application && zip -qur ../aws_lambda_artifact.zip . -x '__pycache__/*' '*.pyc')
unzip -l aws_lambda_artifact.zip | grep -E ' main.py$'

aws lambda create-function --function-name "$FUNCTION_NAME" \
  --runtime python3.11 --architectures x86_64 \
  --handler main.handler --role "$ROLE_ARN" \
  --zip-file fileb://aws_lambda_artifact.zip \
  --memory-size 2048 --timeout 60 --region "$AWS_REGION"
# Zip ≥ 50 MB: súbelo a un bucket S3 y usa --code S3Bucket=<bucket>,S3Key=aws_lambda_artifact.zip

# Para actualizar:
aws lambda update-function-code --function-name "$FUNCTION_NAME" \
  --zip-file fileb://aws_lambda_artifact.zip --region "$AWS_REGION"
```

Luego sigue con los Pasos 6 a 9 (en la limpieza, omite ECR y borra `dependencies/` y el zip). Errores típicos del ZIP:
- `Runtime.ImportModuleError: No module named 'main'`: zipeaste la carpeta `application/` en vez de su contenido.
- `invalid ELF header` o errores de `.so`: dependencias instaladas para macOS o Windows.
- `Unzipped size must be smaller than 262144000 bytes`: pasaste los 250 MB descomprimidos.
