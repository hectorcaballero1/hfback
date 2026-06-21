# HACK//UTEC — Sistema de Triage Inteligente Multitenant

Sistema serverless que clasifica consultas en texto libre. Por cada mensaje, un LLM (Groq) asigna un **veredicto**:

- **`respondido_rag`** — la consulta tiene respuesta en la documentación del tenant; se responde citando la fuente (RAG).
- **`enrutado`** — caso real que necesita un humano; se identifica el área correcta por el contenido.
- **`no_aplica`** — spam o fuera de alcance.

El procesamiento es asíncrono y **multitenant**. Demo con 2 tenants: **UTEC** (universidad) y **Banco Nacional**. Las respuestas `respondido_rag` y los acuses de `enrutado` se notifican por correo (Resend).

## El problema

Toda organización que atiende público recibe **cientos de consultas en texto libre cada día** —
por correo, formularios, chat o mesa de partes. Hoy una persona las lee una por una y decide,
a mano, qué hacer con cada una: responder lo que ya está en un reglamento o FAQ, derivar al
área correcta, o descartar lo que es spam. Ese triage manual es **lento, costoso y propenso a
error**:

- **Demora la primera respuesta:** consultas simples (cuyo dato ya está documentado) esperan en
  cola junto con las complejas.
- **Se pierden o mal-derivan:** un mensaje que llega al buzón equivocado se reenvía varias veces
  o se traspapela. El usuario nunca recibe respuesta.
- **No escala:** en picos (matrícula, cierre de mes) el volumen colapsa al equipo humano.
- **Gasta criterio humano en lo trivial:** personal calificado respondiendo "¿cuánto cuesta la
  constancia?" en vez de atender los casos que de verdad requieren juicio.

## Casos de uso

El sistema es **agnóstico al dominio**: cambia el corpus y las áreas, no la arquitectura. Dos
casos reales en la demo:

- **Universidad (UTEC):** un alumno pregunta por el costo del examen de rezagados → se responde
  al instante citando el reglamento. Otro apela una nota → se enruta a Registro Académico. Un
  spam → se descarta. Áreas: admisiones, registro académico, tesorería, bienestar, sistemas.
- **Banco (Banco Nacional):** un cliente consulta el horario de agencias → respuesta inmediata
  por RAG. Otro reporta un cargo no reconocido → se enruta a Fraudes. Áreas: atención al cliente,
  créditos, operaciones, fraudes, inversiones.

El mismo motor sirve para cualquier organización con documentación y áreas internas (municipio,
hospital, aseguradora, retail).

## Por qué un LLM (y no reglas)

El triage clásico por **palabras clave se rompe apenas el usuario redacta distinto**: "no me llegó
la plata" vs "transferencia no acreditada" significan lo mismo, pero ninguna regla las cubre todas.
Un **LLM entiende la intención** detrás del texto, sin importar cómo esté escrito, y decide entre
responder con documentación (RAG, citando la fuente para no inventar), derivar al área correcta, o
descartar. Esa comprensión semántica es lo que hace viable automatizar un proceso que antes exigía
una persona leyendo cada mensaje.

**Impacto esperado:** menor tiempo de primera respuesta, **cero consultas perdidas** por mal
direccionamiento, y personal humano enfocado solo en lo que requiere criterio —no en lo que ya
está escrito en un reglamento.

## Arquitectura

![Arquitectura del sistema](docs/arquitectura.svg)

Subir corpus para el RAG usa el mismo S3 con otro prefijo (`corpus/`), que dispara la Lambda `ragIngest`. Decisiones de diseño en [docs/arquitectura.md](docs/arquitectura.md).

## Procesamiento masivo y tolerancia a fallos

El sistema está diseñado para **drenar lotes grandes de consultas (20-30+) sin perder ni
un dato**, capturando los errores de la API del LLM y reintentando de forma automática.

**Procesamiento por lotes (asíncrono).** Se sube un JSON con decenas de consultas a S3; el
`fan-out` emite un evento por consulta a EventBridge → SQS. El `worker` las drena de a una
(`reservedConcurrency: 1`, visible en vivo en el dashboard). Cada consulta es independiente:
**una que falle no tumba el resto del lote**.

**Captura de errores del LLM.** El worker distingue dos clases de error:
- **Error de input** (texto vacío/inválido): se marca `fallido` en DynamoDB y se descarta del
  flujo. No se reintenta —reintentarlo nunca lo arreglaría.
- **Error de sistema** (LLM responde `429`, `401`, `500`, timeout o error de red): lanza
  excepción para que la cola lo reintente.

**Reintento automático vía SQS (sin pérdida de datos).** Ante un error de sistema, SQS devuelve
el mensaje a la cola y lo reintenta hasta `maxReceiveCount: 5` (con `VisibilityTimeout` como
backoff). Si tras 5 intentos sigue fallando, el mensaje se mueve **automáticamente a una Dead
Letter Queue (DLQ)**. En ningún punto se pierde la consulta: o termina en DynamoDB (resuelta o
fallida auditable), o queda en la DLQ para reprocesarse (redrive). Una alarma de CloudWatch +
SNS avisa al equipo apenas la DLQ recibe un mensaje.

**Free tier vs. producción (importante).** En la demo, Groq (free tier) impone un límite de
**tokens por minuto**; al subir un lote grande aparecen `429 "too many requests"` transitorios.
**Eso no es un fallo real**: el reintento de SQS los absorbe en segundos y la consulta termina
resolviéndose —es precisamente la tolerancia a fallos en acción. En un entorno productivo con un
**tier de pago no existe ese rate limit** (el proveedor simplemente cobra por uso), así que la
DLQ **no se llenaría de `429`**. Un mensaje en la DLQ en producción significaría un **error
genuino** (proveedor caído, datos corruptos, bug) que **sí amerita revisión manual** —y para eso
existe la alarma. En operación normal, la DLQ debe estar vacía.

## Estructura

```
├── backend/          # Serverless Framework — serverless.yml + handlers + seed_tenants.py
├── rag/              # Docker Compose — Qdrant + FastAPI retrieval + seeder
│   └── corpus/       # Documentos base de cada tenant (txt/md)
├── data/             # JSON de consultas y corpus para la demo
└── docs/             # arquitectura.md, testeo.md, arquitectura.svg (diagrama)
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
