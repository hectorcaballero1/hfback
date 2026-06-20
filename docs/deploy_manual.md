# Deploy — HACK//UTEC

## Orden

1. Levantar la EC2 de RAG (CloudFormation)
2. Configurar `.env`
3. `serverless deploy`
4. Inicializar tenants en DynamoDB

---

## 1. EC2 RAG

### 1a. Crear el stack en la consola

1. CloudFormation → **Create stack** → Upload a template file → subir `rag/cloudformation-ec2.yaml`
2. Continuar hasta **Submit** y esperar `CREATE_COMPLETE`.

El template usa la **VPC default** del Learner Lab automáticamente (igual que el
template de clase) — no pide ningún parámetro de red.

### 1b. Verificar el deploy

Los outputs del stack muestran dónde quedó la instancia (`RagVpcId`,
`RagAvailabilityZone`) y la IP pública. Copiar el output `RagPublicIP`.

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
RESEND_API_KEY=    # resend.com — notificación por correo (opcional)
```

> **Correo (Resend):** los veredictos `respondido_rag` y `enrutado` envían un correo
> al `remitente` de la consulta. En sandbox (sin dominio propio) Resend **solo** acepta
> envíos a tu correo de la cuenta Resend; cualquier otro destinatario lo rechaza, pero
> el envío es fire-and-forget: se loguea y el procesamiento sigue (la consulta igual
> queda en DynamoDB). Para la demo, poné **tu** correo de Resend como `remitente` en las
> consultas que quieras que disparen email. Si dejás `RESEND_API_KEY` vacío, no se
> envía nada y todo sigue funcionando.

## 3. Deploy serverless

Si es la primera vez en esta EC2, instalar Serverless:

```bash
sudo npm install -g serverless@4
```

Luego empaquetar las dependencias de Python y desplegar:

```bash
cd backend
pip install -r requirements.txt -t .   # instala requests en el dir → se sube con el deploy
serverless deploy --stage dev
```

> **Importante:** Serverless v4 NO empaqueta el `requirements.txt` de Python solo.
> El `pip install -t .` deja las librerías en el directorio para que el worker las
> encuentre en runtime. Si lo olvidás, el worker crashea con
> `No module named 'requests'` y las consultas nunca se procesan (quedan en la DLQ).

Guardar la `ApiGatewayUrl` del output — va en el frontend.

## 4. Inicializar tenants

Los tenants viven en `data/tenants.json`. Para agregar uno nuevo, editá ese archivo
(copiá un bloque y cambiá `tenantId`, `nombre` y `areas`) — no hay límite de cantidad.

Luego cargarlos en DynamoDB con un comando (usa las credentials de `~/.aws`):

```bash
cd backend
pip install boto3   # si no está
python seed_tenants.py --stage dev
```

Es idempotente: se puede correr las veces que sea, solo actualiza.

> El front trae `utec` y `banco` hardcodeados como fallback. Para que aparezca un
> 3er tenant tenés que agregarlo en `data/tenants.json` y correr este script — así
> el endpoint `/tenants` lo devuelve y el front lo muestra.

## Probar

```bash
API=https://TU_API_ID.execute-api.us-east-1.amazonaws.com/dev

curl $API/tenants
curl -X POST $API/uploads/presign -H "Content-Type: application/json" -d '{"tenantId":"utec"}'
# subir data/consultas_utec.json con la presigned URL obtenida
curl "$API/stats?tenantId=utec"
```
