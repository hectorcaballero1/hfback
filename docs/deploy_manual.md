# Deploy — HACK//UTEC

## Orden

1. Levantar la EC2 de RAG (CloudFormation)
2. Configurar `.env`
3. `serverless deploy`
4. Inicializar tenants en DynamoDB

---

## 1. EC2 RAG

Subir `rag/cloudformation-ec2.yaml` a CloudFormation en la consola AWS. Parámetros: `VpcId` y `PublicSubnet1` de tu Learner Lab.

Cuando llegue a `CREATE_COMPLETE`, copiar el output `RagPublicIP`.

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

## 2. .env

```bash
cp .env.example .env
```

Completar:
```
ACCOUNT_ID=        # AWS Details del Learner Lab
GROQ_API_KEY=      # console.groq.com
RAG_URL=http://RAG_PUBLIC_IP:8000
```

## 3. Deploy serverless

```bash
cd backend
npm install -g serverless@4
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
