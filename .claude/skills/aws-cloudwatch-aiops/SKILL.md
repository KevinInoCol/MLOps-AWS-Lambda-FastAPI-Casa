---
name: aws-cloudwatch-aiops
description: Centro de operaciones (AIOps) en Amazon CloudWatch para una API desplegada en AWS Lambda con Function URL (como la de aws-lambda-fastapi-deploy) — el equivalente AWS de azure-grafana-aiops cuando Amazon Managed Grafana no está disponible o no conviene. Crea con un script idempotente un dashboard (KPIs de requests, 4xx, 5xx, duración p95, concurrencia y tasa de error; duración con banda de detección de anomalías por ML; requests vs errores; memoria y cold starts con Logs Insights; estado de alarmas; últimos errores), detectores de anomalías y 4 alarmas (5xx, 4xx altos, duración anómala, tráfico anómalo) con aviso opcional por email vía SNS. Incluye un generador de tráfico normal, de errores y de carga para la demo en vivo, y un script de limpieza. Use when the user asks for "monitoreo en AWS", "Grafana en AWS", "AIOps en AWS", "dashboard de CloudWatch", "alarmas para mi Lambda", "detección de anomalías", "monitorear el endpoint", "ver métricas de la API", or types /aws-cloudwatch-aiops.
---

# AIOps con Amazon CloudWatch para una Lambda

Responde **"¿mi API está sana y algo se comporta raro?"** para una función Lambda con Function URL. Funciona en la cuenta de **quien la ejecuta**: el script descubre la función, su URL y su configuración en tiempo de ejecución, sin nada escrito a mano.

Skill pensada para compartir con alumnos: no contiene datos de ninguna cuenta. El email para las alarmas se pasa como argumento y no se guarda en ningún archivo.

Archivos (rutas relativas a la carpeta de esta skill):

| Script | Qué hace |
|---|---|
| `scripts/crear_aiops.py` | Crea o actualiza el dashboard, los detectores de anomalías, las alarmas y, opcionalmente, el SNS. Es idempotente: se puede volver a correr |
| `scripts/generar_trafico.py` | Tráfico `normal`, `errores` y `carga` contra la Function URL. Solo usa la librería estándar |
| `scripts/limpiar_aiops.py` | Borra todo lo anterior. No toca la Lambda |

## ¿Por qué CloudWatch y no Amazon Managed Grafana?

Amazon Managed Grafana existe, pero:
- **Muchas cuentas de organizaciones lo bloquean con una SCP** (`grafana:* ... explicit deny in a service control policy`), y ningún permiso IAM lo arregla. Compruébalo con `aws grafana list-workspaces`.
- **Exige IAM Identity Center** para el login y **cobra por usuario activo** al mes.
- CloudWatch ya trae lo necesario: dashboards, **detección de anomalías por ML integrada**, alarmas nativas y Logs Insights. Sin login extra y por centavos.

| Azure (`/azure-grafana-aiops`) | Esta skill (AWS) |
|---|---|
| Azure Managed Grafana | CloudWatch Dashboard |
| Azure Monitor + Log Analytics | CloudWatch Metrics + Logs |
| KQL `series_decompose_anomalies` | `ANOMALY_DETECTION_BAND` (modelo de ML de CloudWatch) |
| Alertas con umbral dinámico | Alarmas con detección de anomalías |
| Action Group (email) | Tema SNS + suscripción por email |

## Costo (dilo antes de crear)

Valores aproximados; confirma en la página de precios de CloudWatch para tu región:

| Recurso | Costo |
|---|---|
| Dashboard | Los primeros 3 por cuenta son gratis; después ~$3/mes cada uno |
| Alarma estándar (umbral fijo) | ~$0.10/mes |
| Alarma con detección de anomalías | ~$0.30/mes (cuenta como 3 métricas) |
| Consultas de Logs Insights | Por GB escaneado; con los logs de una API de clase es casi $0 |
| SNS por email | Gratis en este volumen |

Total del lab: **alrededor de $1/mes** si se deja creado. Con la limpieza queda en $0.

## Paso 0 — Requisitos

```bash
aws sts get-caller-identity                    # sesión activa (skill /install-aws-cli)
uv --version                                   # para ejecutar con boto3 sin instalar nada (skill /install-uv)
export AWS_REGION=us-east-2                    # la región donde está tu Lambda
export FUNCTION_NAME=api-precio-casas          # tu función
aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --region "$AWS_REGION" --query FunctionUrl --output text
aws cloudwatch list-dashboards --region "$AWS_REGION" >/dev/null && echo "CloudWatch OK"
```

Necesitas una Lambda **con Function URL**. Si aún no la tienes: `/aws-lambda-fastapi-deploy`.

## Paso 1 — Crear el centro de operaciones

Desde la carpeta de la skill (`~/.claude/skills/aws-cloudwatch-aiops` o `.claude/skills/aws-cloudwatch-aiops` del repo):

```bash
uv run --with boto3 python scripts/crear_aiops.py --funcion "$FUNCTION_NAME" --region "$AWS_REGION"
# Con aviso por email (hay que pulsar "Confirm subscription" en el correo que llega):
uv run --with boto3 python scripts/crear_aiops.py --funcion "$FUNCTION_NAME" --region "$AWS_REGION" --email tu-correo@ejemplo.com
```

Imprime el link del dashboard: `https://<región>.console.aws.amazon.com/cloudwatch/home?region=<región>#dashboards/dashboard/aiops-<función>`.

Qué crea (todo con prefijo `aiops-<función>`):

| Recurso | Detalle |
|---|---|
| Dashboard `aiops-<función>` | Ver la tabla de abajo |
| Detectores de anomalías | `Duration` (Average) y `UrlRequestCount` (Sum) |
| Alarma `…-errores-5xx` | `Url5xxCount + Errors ≥ 1` en 1 min: la API falló de verdad |
| Alarma `…-4xx-alto` | `Url4xxCount ≥ 5` en 1 min: clientes mandando CSV inválidos (400/422) |
| Alarma `…-duracion-anomala` | Duración promedio **por encima de la banda** aprendida (ML) |
| Alarma `…-trafico-anomalo` | Requests por minuto **por encima de la banda** aprendida (ML) |
| SNS `aiops-<función>-alertas` | Solo con `--email` |

Paneles del dashboard:

| Fila | Paneles |
|---|---|
| Cabecera | Función, región, memoria, timeout, endpoint y links a la función y a los logs |
| KPIs | Requests · 4xx · 5xx · Duración p95 · Concurrencia máxima (número grande + mini-gráfico) · **Tasa de error %** (medidor con línea en 5 %) |
| Comportamiento | **Duración con banda de anomalía (ML)** · Requests vs 4xx vs 5xx vs errores por minuto |
| Recursos | **Memoria usada vs límite** y **cold starts** (Init Duration), ambos con Logs Insights sobre las líneas `REPORT` · **Estado de alarmas** |
| Logs | Últimos errores y avisos (filtra el `FutureWarning` inofensivo de feature-engine) |

## Paso 2 — Generar tráfico (demo en vivo)

```bash
URL=$(aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --region "$AWS_REGION" --query FunctionUrl --output text)
CSV=Backend-App-Problema-Regresion-Casas/datos_prueba.csv     # un CSV válido para tu API

python3 scripts/generar_trafico.py --url "$URL" --csv "$CSV" --modo normal --minutos 10 --cada 6   # línea base
python3 scripts/generar_trafico.py --url "$URL" --csv "$CSV" --modo errores --n 10                # → alarma 4xx en ~1-2 min
python3 scripts/generar_trafico.py --url "$URL" --csv "$CSV" --modo carga --n 30 --filas 3000 --hilos 10   # → duración y tráfico suben
```

Las métricas tardan **1 a 2 minutos** en aparecer. Pon el dashboard con refresco automático (arriba a la derecha → 1 min) y un rango de 1 hora.

Lo que se ve en la prueba real (API de precio de casas, 2048 MB):
- **Modo `errores`:** la alarma `4xx-alto` pasa a **ALARM** al minuto. `Url4xxCount` sí cuenta los 422 y 400 que devuelve FastAPI.
- **Modo `carga` con 6 a 10 hilos:** Lambda abre **instancias nuevas en paralelo**, y cada una tiene su **cold start** (2 a 4.6 s de Init), visible en la tabla de cold starts. La concurrencia máxima sube a 6. Buen momento para explicar escalado horizontal y cold starts.

## La detección de anomalías necesita historial

Al crearse, los detectores quedan en **`PENDING_TRAINING`** y la banda gris **no aparece todavía**:

```bash
aws cloudwatch describe-anomaly-detectors --region "$AWS_REGION" --namespace AWS/Lambda \
  --query 'AnomalyDetectors[].[SingleMetricAnomalyDetector.MetricName,StateValue]' --output table
```

- El modelo aprende de los datos históricos de la métrica. Con una API recién creada y poco tráfico, tarda en tener suficiente información.
- **Para clase:** crea el lab con anticipación (idealmente el día anterior) y deja `generar_trafico.py --modo normal --minutos 60` corriendo un rato. En la clase lanza `--modo carga` para que la duración se salga de la banda y la alarma `duracion-anomala` se dispare.
- Mientras el modelo entrena, las alarmas de anomalía quedan en `OK` o `INSUFFICIENT_DATA` (los datos faltantes se tratan como "no incumple"). Las de umbral fijo (`5xx`, `4xx`) funcionan desde el primer minuto.

## Paso 3 — Limpieza (al terminar)

```bash
uv run --with boto3 python scripts/limpiar_aiops.py --funcion "$FUNCTION_NAME" --region "$AWS_REGION"
```

Borra el dashboard, las 4 alarmas, los detectores y el tema SNS. **No** borra la Lambda: para eso está el Paso 9 de `/aws-lambda-fastapi-deploy`.

## Solución de problemas

| Síntoma | Causa | Solución |
|---|---|---|
| `explicit deny in a service control policy` | La organización bloquea el servicio o la región | Usa la región permitida (`aws configure get region`) o pide acceso al admin |
| `No encuentro la función` | Nombre o región incorrectos | `aws lambda list-functions --region $AWS_REGION --query 'Functions[].FunctionName'` |
| Paneles Url* vacíos | La función no tiene Function URL, o aún no hay tráfico | Crea la URL (Paso 6 del deploy) y genera tráfico; espera 1-2 min |
| La banda de anomalía no aparece | Detector en `PENDING_TRAINING` | Genera tráfico normal un buen rato; ver la sección de historial |
| La memoria muestra ~1953 MB de límite | Dividiste entre 1048576 | Lambda reporta en múltiplos de 1000: divide entre 1 000 000 (el script ya lo hace) |
| Los 422 no aparecen en los logs | FastAPI no registra los 4xx que devuelve | Se ven en la métrica `Url4xxCount` (panel y alarma 4xx) |
| No llegan emails | Suscripción SNS sin confirmar | Revisa spam y pulsa "Confirm subscription" |
| Paneles de logs vacíos | No hay invocaciones en el rango, o el log group se borró | Amplía el rango de tiempo o genera tráfico |
