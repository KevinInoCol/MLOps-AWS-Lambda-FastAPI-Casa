# ========================================= Método 2: Por Container ===============================================
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
