# HACK//UTEC — Sistema de Triage Inteligente Multitenant

Sistema serverless que clasifica consultas en texto libre. Por cada mensaje, un LLM (Groq) asigna un **veredicto**:

- **`respondido_rag`** — la consulta tiene respuesta en la documentación del tenant; se responde citando la fuente (RAG).
- **`enrutado`** — caso real que necesita un humano; se identifica el área correcta por el contenido.
- **`no_aplica`** — spam o fuera de alcance.

El procesamiento es asíncrono y **multitenant**. Demo con 2 tenants: **UTEC** (universidad) y **Banco Nacional**. Las respuestas `respondido_rag` y los acuses de `enrutado` se notifican por correo (Resend).

## Arquitectura

```
S3 → fan-out → EventBridge → SQS → worker (Groq) → DynamoDB → Resend (email)
                                       ↕
                                  EC2 (RAG: Qdrant + FastAPI)
```

Subir corpus para el RAG usa el mismo S3 con otro prefijo (`corpus/`), que dispara la Lambda `ragIngest`. Diagrama y decisiones de diseño en [docs/arquitectura.md](docs/arquitectura.md).

## Estructura

```
├── backend/          # Serverless Framework — serverless.yml + handlers + seed_tenants.py
├── rag/              # Docker Compose — Qdrant + FastAPI retrieval + seeder
│   └── corpus/       # Documentos base de cada tenant (txt/md)
├── data/             # JSON de consultas y corpus para la demo
└── docs/             # arquitectura.md
```

## Deploy

Todo corre en una sola EC2 (la del RAG): ahí se levanta el RAG con Docker y desde ahí
mismo se hace el `serverless deploy` del backend.

### 1. Crear la EC2 con CloudFormation

Subir `rag/cloudformation-ec2.yaml` a la consola de CloudFormation y crear el stack
(usa la **VPC default**, no pide parámetros). Cuando llegue a `CREATE_COMPLETE`, copiar
el output `RagPublicIP` y hacer SSH a la máquina.

### 2. Dentro de la EC2: credenciales, Serverless y RAG

```bash
# a. Credenciales del Learner Lab (expiran cada sesión)
#    → pegar en ~/.aws/credentials desde AWS Details → AWS CLI

# b. Serverless v4 (el AMI no lo trae; v4 requiere org)
sudo npm install -g serverless@4
serverless login

# c. Levantar el RAG con Docker
cd ~/hfback/rag
docker compose up -d qdrant retrieval
docker compose run seeder          # siembra el corpus base
curl http://localhost:8000/health  # verificar
```

### 3. Configurar `.env` y desplegar el backend

El `.env` vive en `backend/`, junto al `serverless.yml` (Serverless lo lee solo):

```bash
cd ~/hfback/backend
cp .env.example .env      # completar (ver tabla abajo)
```

| Variable | Para qué |
|---|---|
| `SLS_ORG` | tu org de [app.serverless.com](https://app.serverless.com) |
| `ACCOUNT_ID` | AWS Account ID del Learner Lab |
| `GROQ_API_KEY` | LLM — [console.groq.com](https://console.groq.com) |
| `RAG_URL` | IP **pública** de esta EC2 (ej. `http://1.2.3.4:8000`) — la Lambda llama por internet, no `localhost` |
| `ALARM_EMAIL` | correo que recibe la alarma de la DLQ (obligatorio, sin default) |
| `RESEND_API_KEY` | correos (opcional) — [resend.com](https://resend.com) |

```bash
pip install -r requirements.txt -t .   # IMPRESCINDIBLE: si falta, el worker crashea con "No module named 'requests'"
serverless deploy
```

Tras el deploy: confirmar la **suscripción SNS** (llega un correo de AWS a `ALARM_EMAIL`)
y guardar la `ApiGatewayUrl` del output — va en el `.env` del frontend (`VITE_API_URL`).

### 4. Inicializar tenants (DynamoDB)

```bash
python seed_tenants.py    # lee data/tenants.json; idempotente
```

## API

Base: `https://{api-id}.execute-api.us-east-1.amazonaws.com/dev` · todos con CORS y JSON.

| Endpoint | Qué devuelve |
|---|---|
| `GET /tenants` | `{ tenants: [{ tenantId, nombre }] }` — selector |
| `POST /uploads/presign` | `{ uploadUrl, key }` — body `{ tenantId, tipo }` (`consultas`\|`documentos`) |
| `GET /stats?tenantId=` | `{ estados:{pendiente,procesando,resuelto,fallido}, veredictos:{...}, total }` |
| `GET /consultas?tenantId=&estado=&veredicto=&limit=&cursor=` | `{ items:[...], nextCursor, count }` |
| `GET /consultas/{id}?tenantId=` | un item; `404 { error: "not_found" }` |

**Campos de un item:** `consultaId, texto, remitente, estado, veredicto, area, respuesta, fuente, motivo, modelo, confianza, reintentos, timestamp, updatedAt`. `area` solo en `enrutado`; `respuesta`+`fuente` solo en `respondido_rag`; `motivo` solo en `fallido`.

**Flujo de subida (presign → PUT directo a S3):**

```
POST /uploads/presign { tenantId, tipo } → { uploadUrl }
PUT {uploadUrl}  (Content-Type: application/json)
```

JSON de **consultas** (`tipo=consultas` → triage):
```json
{ "tenantId": "utec", "consultas": [ { "id": "c-001", "texto": "...", "remitente": "..." } ] }
```

JSON de **corpus** (`tipo=documentos` → ingesta al RAG, en caliente):
```json
{ "tenantId": "utec", "documentos": [ { "fuente": "faq.txt", "texto": "..." } ] }
```

## Stack técnico

- **Backend:** Serverless Framework v4, Python 3.12, AWS Lambda
- **Mensajería:** S3, EventBridge, SQS (con DLQ + alarma CloudWatch/SNS)
- **Base de datos:** DynamoDB (tabla única, GSI por estado)
- **LLM:** Groq (llama-3.1-8b-instant)
- **RAG:** Qdrant + sentence-transformers all-MiniLM-L6-v2 (local, sin API externa)
- **Email:** Resend (notificación de respuestas)
- **Infra:** AWS Academy Learner Lab con LabRole

## Testeo

Flujo de prueba end-to-end (consultas base → corpus en caliente → consulta estrella RAG)
y cómo forzar la DLQ para demostrar la alarma: ver [docs/testeo.md](docs/testeo.md).
