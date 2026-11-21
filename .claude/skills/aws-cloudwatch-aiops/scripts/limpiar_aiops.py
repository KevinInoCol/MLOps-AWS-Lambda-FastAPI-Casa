"""Borra todo lo que crea crear_aiops.py para una función: dashboard, alarmas, detectores de anomalías y tema SNS.

No toca la función Lambda, su URL ni sus logs (eso se borra con el Paso 9 de aws-lambda-fastapi-deploy).

Uso:
  uv run --with boto3 python limpiar_aiops.py --funcion api-precio-casas [--region us-east-2]
"""

import argparse

import boto3
from botocore.exceptions import ClientError

PREFIJO = "aiops"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--funcion", required=True)
    p.add_argument("--region", default=None)
    a = p.parse_args()

    sesion = boto3.Session(region_name=a.region)
    cw, sns = sesion.client("cloudwatch"), sesion.client("sns")
    print(f"Limpiando AIOps de '{a.funcion}' en {sesion.region_name}")

    nombre = f"{PREFIJO}-{a.funcion}"
    try:
        cw.delete_dashboards(DashboardNames=[nombre])
        print(f"  Dashboard borrado: {nombre}")
    except ClientError:
        print(f"  Dashboard {nombre}: no existía")

    alarmas = [m["AlarmName"] for pag in cw.get_paginator("describe_alarms").paginate(AlarmNamePrefix=f"{nombre}-")
               for m in pag["MetricAlarms"]]
    if alarmas:
        cw.delete_alarms(AlarmNames=alarmas)
    print(f"  Alarmas borradas: {len(alarmas)}")

    detectores = cw.describe_anomaly_detectors(
        Namespace="AWS/Lambda", Dimensions=[{"Name": "FunctionName", "Value": a.funcion}])["AnomalyDetectors"]
    for d in detectores:
        cw.delete_anomaly_detector(SingleMetricAnomalyDetector=d["SingleMetricAnomalyDetector"])
    print(f"  Detectores de anomalías borrados: {len(detectores)}")

    tema = f"{PREFIJO}-{a.funcion}-alertas"
    temas = [t["TopicArn"] for pag in sns.get_paginator("list_topics").paginate() for t in pag["Topics"]
             if t["TopicArn"].endswith(f":{tema}")]
    for arn in temas:
        sns.delete_topic(TopicArn=arn)
    print(f"  Temas SNS borrados: {len(temas)}")

    restantes = cw.describe_alarms(AlarmNamePrefix=f"{nombre}-")["MetricAlarms"]
    print("Listo: no queda nada del lab." if not restantes else f"Atención: quedan {len(restantes)} alarmas.")


if __name__ == "__main__":
    main()
