# Deploy — HACK//UTEC

## Orden

1. Levantar la EC2 de RAG (CloudFormation)
2. Configurar `.env`
3. `serverless deploy`
4. Inicializar tenants en DynamoDB

---

## 1. EC2 RAG

### 1a. Obtener VpcId y PublicSubnet1

Antes de crear el stack en la consola, consultar qué valores usar:

```bash
# VPC default (Learner Lab solo tiene una)
aws ec2 describe-vpcs --query "Vpcs[].VpcId" --output text

# Subnets públicas (MapPublicIpOnLaunch=true)
aws ec2 describe-subnets --query "Subnets[?MapPublicIpOnLaunch].SubnetId" --output text
```

> **Learner Lab:** usar la VPC default y cualquier subnet con `MapPublicIpOnLaunch=true`.
> Los parámetros no tienen Default para forzar que siempre se especifiquen
> explícitamente — evita desplegar en la VPC equivocada.

### 1b. Crear el stack en la consola

1. CloudFormation → **Create stack** → Upload a template file → subir `rag/cloudformation-ec2.yaml`
2. En la pantalla de parámetros ingresar:
   - `VpcId` → el valor obtenido arriba
   - `PublicSubnet1` → la subnet obtenida arriba
3. Continuar hasta **Submit** y esperar `CREATE_COMPLETE`.

### 1c. Verificar el deploy

Los outputs del stack muestran en qué VPC/subnet quedó la instancia (`RagVpcId`,
`RagSubnetId`) además de la IP pública. Copiar el output `RagPublicIP`.

SSH para levantar el RAG:
```bash
ssh -i vockey.pem ubuntu@RAG_PUBLIC_IP
git clone https://github.com/tu-usuario/hack-utec.git
cd hack-utec/rag
docker compose up -d qdrant retrieval
docker compose run seeder
```

Verificar:
```bash
curl http://localhost:8000/health
```

## 2. Credentials AWS y .env

Las credentials del Learner Lab expiran cada sesión. Actualizarlas en `~/.aws/credentials`:

```
[default]
aws_access_key_id=ASIA...
aws_secret_access_key=...
aws_session_token=...
```

Copiar los valores desde **AWS Details → Cloud Access → AWS CLI** en el Learner Lab.

Luego configurar el `.env`:

```bash
cp .env.example .env
```

Completar:
```
SLS_ORG=           # nombre de tu org en app.serverless.com
ACCOUNT_ID=        # AWS Details del Learner Lab
GROQ_API_KEY=      # console.groq.com
RAG_URL=http://IP_PUBLICA_EC2_RAG:8000
```

## 3. Deploy serverless

Si es la primera vez en esta EC2, instalar Serverless:

```bash
sudo npm install -g serverless@4
```

Luego desplegar:

```bash
cd backend
serverless deploy --stage dev
```

Guardar la `ApiGatewayUrl` del output — va en el frontend.

## 4. Inicializar tenants

```bash
TABLE="hack-utec-triage-dev"

aws dynamodb put-item --table-name $TABLE --item '{
  "pk":{"S":"utec#config"},"sk":{"S":"CONFIG"},
  "tenantId":{"S":"utec"},"nombre":{"S":"UTEC"},
  "areas":{"L":[{"S":"admisiones"},{"S":"registro_academico"},{"S":"tesoreria"},{"S":"bienestar"},{"S":"sistemas"}]}
}'

aws dynamodb put-item --table-name $TABLE --item '{
  "pk":{"S":"banco#config"},"sk":{"S":"CONFIG"},
  "tenantId":{"S":"banco"},"nombre":{"S":"Banco Nacional"},
  "areas":{"L":[{"S":"atencion_cliente"},{"S":"creditos"},{"S":"operaciones"},{"S":"fraudes"},{"S":"inversiones"}]}
}'
```

## Probar

```bash
API=https://TU_API_ID.execute-api.us-east-1.amazonaws.com/dev

curl $API/tenants
curl -X POST $API/uploads/presign -H "Content-Type: application/json" -d '{"tenantId":"utec"}'
# subir data/consultas_utec.json con la presigned URL obtenida
curl "$API/stats?tenantId=utec"
```
