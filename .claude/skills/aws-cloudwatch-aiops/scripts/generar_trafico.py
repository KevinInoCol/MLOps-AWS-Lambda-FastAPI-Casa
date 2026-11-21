"""Genera tráfico contra la API (Function URL) para ver el dashboard y las alarmas en acción.

Modos:
  normal   requests válidas espaciadas (línea base para que la detección de anomalías aprenda)
  errores  CSV con columnas de otro dataset (422) y archivos que no son CSV (400) → alarma 4xx
  carga    CSV grandes (miles de filas) en ráfagas concurrentes → sube duración y tráfico (anomalías)

Uso:
  python generar_trafico.py --url https://<id>.lambda-url.<region>.on.aws --csv datos_prueba.csv --modo normal --minutos 10
  python generar_trafico.py --url ... --csv datos_prueba.csv --modo errores --n 20
  python generar_trafico.py --url ... --csv datos_prueba.csv --modo carga --n 40 --filas 3000 --hilos 10

Solo usa la librería estándar de Python (no hace falta instalar nada).
"""

import argparse
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

RUTA = "/obtener-datos-de-usuario-y-predecir"


def multipart(nombre, contenido, tipo):
    limite = uuid.uuid4().hex
    cuerpo = (f"--{limite}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{nombre}\"\r\n"
              f"Content-Type: {tipo}\r\n\r\n").encode() + contenido + f"\r\n--{limite}--\r\n".encode()
    return cuerpo, f"multipart/form-data; boundary={limite}"


def enviar(url, nombre, contenido, tipo="text/csv"):
    cuerpo, ctype = multipart(nombre, contenido, tipo)
    req = urllib.request.Request(url + RUTA, data=cuerpo, headers={"Content-Type": ctype}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            r.read()
            return r.status, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0
    except Exception:
        return "sin respuesta", time.time() - t0


def csv_grande(base, filas):
    lineas = base.decode().strip().splitlines()
    cabecera, datos = lineas[0], lineas[1:]
    cuerpo = [datos[i % len(datos)] for i in range(filas)]
    return ("\n".join([cabecera] + cuerpo) + "\n").encode()


def resumen(etiqueta, resultados):
    codigos = Counter(str(c) for c, _ in resultados)
    tiempos = sorted(t for _, t in resultados)
    p95 = tiempos[int(len(tiempos) * 0.95) - 1] if tiempos else 0
    print(f"{etiqueta}: {len(resultados)} requests · códigos {dict(codigos)} · p95 cliente {p95:.2f}s")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True, help="Function URL (con o sin / final)")
    p.add_argument("--csv", required=True, help="CSV válido de ejemplo (p. ej. datos_prueba.csv)")
    p.add_argument("--modo", choices=["normal", "errores", "carga"], default="normal")
    p.add_argument("--minutos", type=float, default=5, help="normal: duración total")
    p.add_argument("--cada", type=float, default=6, help="normal: segundos entre requests")
    p.add_argument("--n", type=int, default=20, help="errores/carga: cantidad de requests")
    p.add_argument("--filas", type=int, default=3000, help="carga: filas por CSV")
    p.add_argument("--hilos", type=int, default=10, help="carga: requests simultáneas")
    a = p.parse_args()

    url = a.url.rstrip("/")
    base = open(a.csv, "rb").read()

    if a.modo == "normal":
        fin, res = time.time() + a.minutos * 60, []
        while time.time() < fin:
            res.append(enviar(url, "datos.csv", base))
            print(f"  {time.strftime('%H:%M:%S')} → {res[-1][0]} ({res[-1][1]:.2f}s)", flush=True)
            time.sleep(a.cada)
        resumen("normal", res)

    elif a.modo == "errores":
        otro_dataset = b"bedrooms,bathrooms,sqft_living,zipcode,lat,long\n3,1,1180,98178,47.51,-122.25\n"
        no_csv = b"\x89PNG\r\n\x1a\n esto no es un csv"
        tareas = [("otro.csv", otro_dataset, "text/csv") if i % 2 == 0 else ("foto.png", no_csv, "image/png")
                  for i in range(a.n)]
        with ThreadPoolExecutor(5) as ex:
            res = list(ex.map(lambda t: enviar(url, *t), tareas))
        resumen("errores (esperado: 422 y 400)", res)

    else:
        grande = csv_grande(base, a.filas)
        print(f"  CSV de carga: {a.filas} filas · {len(grande) / 1024:.0f} KB")
        with ThreadPoolExecutor(a.hilos) as ex:
            res = list(ex.map(lambda _: enviar(url, "grande.csv", grande), range(a.n)))
        resumen("carga", res)


if __name__ == "__main__":
    main()
