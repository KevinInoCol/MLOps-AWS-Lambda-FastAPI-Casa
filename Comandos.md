#============================================= Método 1: por ZIP ======================================================
#Paso 0 - Activar el entorno:
conda activate MLOps-AWS-Lambda-API-Regresion

#Paso 1 - Instalar dependencias compatibles con Lambda
pip3 install -t dependencies -r requirements.txt --platform manylinux2014_x86_64 --implementation cp --python-version 3.11 --only-binary=:all: --upgrade

  - -t dependencies → instala en la carpeta dependencies/ (no en el entorno).
  - --platform manylinux2014_x86_64 → binarios para Linux x86_64 (la arquitectura de Lambda).
  - --implementation cp → CPython.
  - --python-version 3.11 → versión de Python que usa tu Lambda.
  - --only-binary=:all: → prohíbe compilar desde código fuente (evita que tu Mac compile binarios de macOS que Lambda no puede ejecutar). 
  - --upgrade → actualiza si ya existían.

#Paso 2 — Empaquetar las dependencias en el ZIP :
cd dependencies; zip ../aws_lambda_artifact.zip -r .

#Paso 3 — Añadir el código de la app al ZIP
# El código vive en application/, pero se zipea DESDE DENTRO de esa carpeta
# para que main.py, configuraciones/, input/ y el modelo queden en la RAÍZ del ZIP
# (que es lo que Lambda espera en /var/task). NO se crea ninguna carpeta application/ dentro del ZIP.
cd application; zip ../aws_lambda_artifact.zip -u main.py precio_casas_pipeline.joblib -r configuraciones input


#============================================ Método 2: Por Container ==================================================
# Despliegue con Docker y ECR
Paso 1: Instalar Docker.
Paso 2: Instalar la CLI de AWS.
Paso 3: aws configure
  - AWS Access Key ID [None]:
  - AWS Secret Access Key [None]:
  - Default region name [None]: us-east-1
  - Default output format [None]: json
Paso 4: Crear un Repositorio en ECR (Elastic Container Registry).
Paso 5: Colocar los comandos de envío de la Imagen hacia el Repositorio:
  - Copiar y pegar el primer comando
  - No uses el segundo comando, usa este: docker build --platform linux/amd64 -t appfastapi/modelo_regresion .
  - Copiar y pegar el segundo comando
  - Copiar y pegar el tercer comando
