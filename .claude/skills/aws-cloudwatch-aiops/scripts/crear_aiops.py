"""Crea el centro de operaciones (AIOps) en CloudWatch para una función Lambda con Function URL.

Crea (o actualiza, es idempotente):
  - Dashboard  aiops-<funcion>         KPIs, duración con banda de anomalía, tráfico/errores,
                                       memoria y cold starts (Logs Insights), estado de alarmas
  - Detectores de anomalías (ML)       Duration (Average) y UrlRequestCount (Sum)
  - Alarmas    aiops-<funcion>-*       errores 5xx, 4xx altos, duración anómala, tráfico anómalo
  - (opcional) Tema SNS + suscripción por email para recibir las alarmas

Uso:
  uv run --with boto3 python crear_aiops.py --funcion api-precio-casas [--region us-east-2] [--email tu@correo]

No guarda ningún dato de la cuenta en archivos: todo se descubre en tiempo de ejecución.
"""

import argparse
import json
import sys

import boto3
from botocore.exceptions import ClientError

PREFIJO = "aiops"
TAG = {"Key": "lab", "Value": "aws-cloudwatch-aiops"}
PERIODO = 60  # segundos: resolución de métricas y alarmas


def args_cli():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--funcion", required=True, help="Nombre de la función Lambda")
    p.add_argument("--region", default=None, help="Región (por defecto, la de aws configure)")
    p.add_argument("--email", default=None, help="Email para avisos de alarma (opcional; hay que confirmar la suscripción)")
    return p.parse_args()


def metrica(nombre, funcion, **extra):
    return ["AWS/Lambda", nombre, "FunctionName", funcion, extra] if extra else ["AWS/Lambda", nombre, "FunctionName", funcion]


def crear_sns(sesion, funcion, email):
    sns = sesion.client("sns")
    arn = sns.create_topic(Name=f"{PREFIJO}-{funcion}-alertas", Tags=[TAG])["TopicArn"]
    if email:
        sns.subscribe(TopicArn=arn, Protocol="email", Endpoint=email)
        print("  SNS: suscripción creada → revisa tu correo y pulsa 'Confirm subscription'")
    return arn


def crear_detectores(cw, funcion):
    for nombre, stat in (("Duration", "Average"), ("UrlRequestCount", "Sum")):
        cw.put_anomaly_detector(SingleMetricAnomalyDetector={
            "Namespace": "AWS/Lambda", "MetricName": nombre, "Stat": stat,
            "Dimensions": [{"Name": "FunctionName", "Value": funcion}],
        })
        print(f"  Detector de anomalías: {nombre} ({stat})")


def crear_alarmas(cw, funcion, sns_arn):
    acciones = {"AlarmActions": [sns_arn], "OKActions": [sns_arn]} if sns_arn else {}
    dims = [{"Name": "FunctionName", "Value": funcion}]

    def m(id_, nombre, stat, visible=False):
        return {"Id": id_, "ReturnData": visible, "MetricStat": {
            "Metric": {"Namespace": "AWS/Lambda", "MetricName": nombre, "Dimensions": dims},
            "Period": PERIODO, "Stat": stat}}

    alarmas = [
        dict(  # 5xx de la URL + errores de la función (excepciones, timeouts)
            AlarmName=f"{PREFIJO}-{funcion}-errores-5xx",
            AlarmDescription="La API devolvió 5xx o la función falló (excepción, timeout, memoria).",
            Metrics=[m("m5xx", "Url5xxCount", "Sum"), m("merr", "Errors", "Sum"),
                     {"Id": "e1", "Expression": "FILL(m5xx,0)+FILL(merr,0)", "Label": "5xx + Errors", "ReturnData": True}],
            ComparisonOperator="GreaterThanOrEqualToThreshold", Threshold=1,
            EvaluationPeriods=1, DatapointsToAlarm=1),
        dict(  # clientes enviando CSV inválidos (400/422) o 403
            AlarmName=f"{PREFIJO}-{funcion}-4xx-alto",
            AlarmDescription="Muchas respuestas 4xx en un minuto: CSV inválidos, columnas faltantes o permisos.",
            Metrics=[m("m4xx", "Url4xxCount", "Sum", visible=True)],
            ComparisonOperator="GreaterThanOrEqualToThreshold", Threshold=5,
            EvaluationPeriods=1, DatapointsToAlarm=1),
        dict(  # ML: la duración se sale de la banda normal aprendida
            AlarmName=f"{PREFIJO}-{funcion}-duracion-anomala",
            AlarmDescription="La duración promedio se salió por arriba de la banda normal (detección de anomalías).",
            Metrics=[m("m1", "Duration", "Average", visible=True),
                     {"Id": "ad1", "Expression": "ANOMALY_DETECTION_BAND(m1, 2)", "Label": "Banda normal", "ReturnData": True}],
            ThresholdMetricId="ad1", ComparisonOperator="GreaterThanUpperThreshold",
            EvaluationPeriods=1, DatapointsToAlarm=1),
        dict(  # ML: picos de tráfico fuera de lo normal
            AlarmName=f"{PREFIJO}-{funcion}-trafico-anomalo",
            AlarmDescription="Las requests por minuto se salieron por arriba de la banda normal (detección de anomalías).",
            Metrics=[m("m1", "UrlRequestCount", "Sum", visible=True),
                     {"Id": "ad1", "Expression": "ANOMALY_DETECTION_BAND(m1, 2)", "Label": "Banda normal", "ReturnData": True}],
            ThresholdMetricId="ad1", ComparisonOperator="GreaterThanUpperThreshold",
            EvaluationPeriods=1, DatapointsToAlarm=1),
    ]
    arns = []
    for a in alarmas:
        cw.put_metric_alarm(TreatMissingData="notBreaching", Tags=[TAG], **acciones, **a)
        arns.append(cw.describe_alarms(AlarmNames=[a["AlarmName"]])["MetricAlarms"][0]["AlarmArn"])
        print(f"  Alarma: {a['AlarmName']}")
    return arns


def dashboard(funcion, region, url, arns, config):
    log_group = f"/aws/lambda/{funcion}"
    fuente = f"SOURCE '{log_group}'"
    consola = f"https://{region}.console.aws.amazon.com"
    w = []

    def add(tipo, x, y, ancho, alto, props):
        w.append({"type": tipo, "x": x, "y": y, "width": ancho, "height": alto, "properties": props})

    # Fila 0 — cabecera
    add("text", 0, 0, 24, 2, {"background": "transparent", "markdown": (
        f"## 🏠 AIOps · `{funcion}`  \n"
        f"**Región** `{region}` · **Memoria** {config['MemorySize']} MB · **Timeout** {config['Timeout']} s · "
        f"**Endpoint** `{url}` · "
        f"[Función]({consola}/lambda/home?region={region}#/functions/{funcion}) · "
        f"[Logs]({consola}/cloudwatch/home?region={region}#logsV2:log-groups/log-group/{log_group.replace('/', '$252F')})"
    )})

    # Fila 1 — KPIs (número grande + mini-gráfico)
    kpis = [
        ("Requests", [metrica("UrlRequestCount", funcion, label="Requests")], "Sum"),
        ("Errores cliente (4xx)", [metrica("Url4xxCount", funcion, label="4xx", color="#F0B85C")], "Sum"),
        ("Errores servidor (5xx)", [metrica("Url5xxCount", funcion, label="5xx", color="#F0776E")], "Sum"),
        ("Duración p95 (ms)", [metrica("Duration", funcion, label="p95", stat="p95")], "p95"),
        ("Concurrencia máx.", [metrica("ConcurrentExecutions", funcion, label="Máx.", stat="Maximum")], "Maximum"),
    ]
    for i, (titulo, ms, stat) in enumerate(kpis):
        add("metric", i * 4, 2, 4, 4, {"title": titulo, "view": "singleValue", "sparkline": True,
                                         "region": region, "stat": stat, "period": PERIODO, "metrics": ms})
    add("metric", 20, 2, 4, 4, {"title": "Tasa de error (%)", "view": "gauge", "region": region, "period": PERIODO,
        "stat": "Sum", "yAxis": {"left": {"min": 0, "max": 100}}, "setPeriodToTimeRange": True,
        "metrics": [
            [{"expression": "100*(FILL(m4,0)+FILL(m5,0))/IF(mr>0, mr, 1)", "label": "Error %", "id": "e1"}],
            metrica("UrlRequestCount", funcion, id="mr", visible=False),
            metrica("Url4xxCount", funcion, id="m4", visible=False),
            metrica("Url5xxCount", funcion, id="m5", visible=False)],
        "annotations": {"horizontal": [{"value": 5, "label": "5 %", "color": "#F0B85C"}]}})

    # Fila 2 — duración con banda de anomalías + tráfico vs errores
    add("metric", 0, 6, 12, 6, {"title": "Duración promedio (ms) · banda de anomalía (ML)", "view": "timeSeries",
        "region": region, "period": PERIODO, "stat": "Average",
        "metrics": [
            [{"expression": "ANOMALY_DETECTION_BAND(m1, 2)", "label": "Banda normal", "id": "ad1", "color": "#95A5A6"}],
            metrica("Duration", funcion, id="m1", label="Duración promedio", color="#FF7A50"),
            metrica("Duration", funcion, label="p95", stat="p95", color="#6FD3C7")],
        "yAxis": {"left": {"min": 0, "label": "ms", "showUnits": False}}})
    add("metric", 12, 6, 12, 6, {"title": "Requests vs errores por minuto", "view": "timeSeries", "stacked": False,
        "region": region, "period": PERIODO, "stat": "Sum",
        "metrics": [
            metrica("UrlRequestCount", funcion, label="Requests", color="#6FD3C7"),
            metrica("Url4xxCount", funcion, label="4xx", color="#F0B85C"),
            metrica("Url5xxCount", funcion, label="5xx", color="#F0776E"),
            metrica("Errors", funcion, label="Errores de la función", color="#C0392B")]})

    # Fila 3 — memoria y cold starts (desde las líneas REPORT) + estado de alarmas
    add("log", 0, 12, 8, 6, {"title": "Memoria usada vs límite (MB)", "region": region, "view": "timeSeries",
        "query": f"{fuente} | filter @type = \"REPORT\" "
                 f"| stats max(@maxMemoryUsed/1000000) as MemoriaUsadaMB, max(@memorySize/1000000) as LimiteMB by bin(5m)"})
    add("log", 8, 12, 8, 6, {"title": "Cold starts (Init Duration)", "region": region, "view": "table",
        "query": f"{fuente} | filter @type = \"REPORT\" and ispresent(@initDuration) "
                 f"| fields @timestamp, round(@initDuration) as InitMs, round(@duration) as DuracionMs, "
                 f"round(@maxMemoryUsed/1000000) as MemoriaMB | sort @timestamp desc | limit 20"})
    add("alarm", 16, 12, 8, 6, {"title": "Estado de alarmas", "alarms": arns, "sortBy": "stateUpdatedTimestamp"})

    # Fila 4 — últimos errores y avisos en los logs
    add("log", 0, 18, 24, 6, {"title": "Últimos errores y avisos en los logs", "region": region, "view": "table",
        "query": f"{fuente} | filter @message like /(?i)(traceback|error|exception|timed out|status: timeout|warning)/ "
                 f"and @message not like /FutureWarning|X\\.loc\\[/ | fields @timestamp, @message | sort @timestamp desc | limit 25"})
    return {"start": "-PT3H", "periodOverride": "inherit", "widgets": w}


def main():
    a = args_cli()
    sesion = boto3.Session(region_name=a.region)
    region = sesion.region_name
    if not region:
        sys.exit("Define la región con --region o con aws configure.")
    lam, cw = sesion.client("lambda"), sesion.client("cloudwatch")

    try:
        config = lam.get_function_configuration(FunctionName=a.funcion)
    except ClientError as e:
        sys.exit(f"No encuentro la función '{a.funcion}' en {region}: {e.response['Error']['Message']}")
    try:
        url = lam.get_function_url_config(FunctionName=a.funcion)["FunctionUrl"]
    except ClientError:
        url = "(sin Function URL)"
        print("  Aviso: la función no tiene Function URL; los paneles Url* quedarán vacíos.")

    print(f"Función: {a.funcion} · región {region}")
    sns_arn = crear_sns(sesion, a.funcion, a.email) if a.email else None
    crear_detectores(cw, a.funcion)
    arns = crear_alarmas(cw, a.funcion, sns_arn)

    nombre = f"{PREFIJO}-{a.funcion}"
    cw.put_dashboard(DashboardName=nombre, DashboardBody=json.dumps(dashboard(a.funcion, region, url, arns, config)))
    print(f"  Dashboard: {nombre}")
    print(f"\nAbre el dashboard:\nhttps://{region}.console.aws.amazon.com/cloudwatch/home?region={region}#dashboards/dashboard/{nombre}")


if __name__ == "__main__":
    main()
