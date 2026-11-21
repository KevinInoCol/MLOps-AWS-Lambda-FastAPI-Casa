# Imagen base oficial de AWS Lambda (trae el runtime y el emulador para pruebas locales)
FROM public.ecr.aws/lambda/python:3.11

# 1. Dependencias primero: si solo cambia el código, Docker reutiliza esta capa
# --only-binary=:all: → solo wheels precompilados. La imagen python:3.11 corre sobre
#   Amazon Linux 2 (glibc 2.26) y NO trae gcc: si una librería no tiene wheel compatible,
#   el build falla en vez de intentar compilarla.
COPY requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt --target "${LAMBDA_TASK_ROOT}"

# 2. Código y modelo: el CONTENIDO de application/ va a la raíz de /var/task
COPY application/ ${LAMBDA_TASK_ROOT}

# 3. Handler de Lambda: archivo main.py, objeto handler (Mangum)
CMD [ "main.handler" ]
