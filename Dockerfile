FROM public.ecr.aws/lambda/python:3.11

# Copiamos requirements
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# 1. Actualizamos pip (importante para que detecte los archivos de Linux)
RUN pip install --upgrade pip

# 2. Instalamos PROHIBIENDO la compilación (--only-binary=:all:)
# Esto evitará el error de "gcc" o "cc not found"
RUN pip install -r requirements.txt --only-binary=:all: --platform manylinux2014_x86_64 --target "${LAMBDA_TASK_ROOT}"

# Copiamos el código de la app (main.py, modelo, carpetas).
# Está en application/, pero copiamos su CONTENIDO a la raíz de /var/task
# para que los imports (configuraciones, input) y la carga del modelo funcionen.
COPY application/ ${LAMBDA_TASK_ROOT}

CMD [ "main.handler" ]