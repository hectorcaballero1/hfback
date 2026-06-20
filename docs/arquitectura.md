# Arquitectura — HACK//UTEC Triage Inteligente

## Diagrama

```
                    ┌─────────┐
                    │ Frontend│
                    │ (React) │
                    └────┬────┘
                         │ POST /uploads/presign
                         │ GET /stats (polling)
                         │ GET /consultas
                         ▼
                  ┌──────────────┐
                  │  API Gateway │
                  └──────┬───────┘
                         │
              ┌──────────┼──────────────────┐
              │          │                  │
         presign.py  stats.py         consultas.py
                         │             tenants.py
                         │
                    ┌────┴────┐
                    │   S3    │  ← Frontend sube JSON con presigned URL
                    └────┬────┘
                         │ s3:ObjectCreated (filtrado por prefijo)
              ┌──────────┴──────────┐
       consultas/                corpus/
              │                      │
              ▼                      ▼
       ┌─────────────┐       ┌──────────────┐
       │ fanout.py   │       │ ragingest.py │  Reenvía cada doc al RAG
       │  (Lambda)   │       │  (Lambda)    │  POST /documentos
       └──────┬──────┘       └──────┬───────┘
              │                     │ (ingesta corpus en caliente)
              │                     ▼  EC2 RAG: chunk + embed + upsert Qdrant
              │  Lee JSON, emite 1 evento por consulta
                         │ put_events
                         ▼
                  ┌──────────────┐
                  │ EventBridge  │  bus: hack-utec-bus
                  │  Bus + Rule  │  detail-type: consulta.recibida
                  └──────┬───────┘
                         │ SQS target (resource-based policy)
                         ▼
              ┌───────────────────┐
              │  SQS Queue        │  visibilityTimeout: 360s
              │  (hack-utec-queue)│  maxReceiveCount: 5
              └──────┬────────────┘
                     │ trigger (batchSize: 1)
                     ▼           ┌──────────┐
              ┌─────────────┐    │   DLQ    │ ← solo errores transitorios
              │ worker.py   │    │          │   tras 5 reintentos
              │  (Lambda)   │    └──────────┘
              │ concurrency=1│
              └──────┬───────┘
                     │
          ┌──────────┼──────────────┐
          │          │              │
          ▼          ▼              ▼
    enrutado   no_aplica    respondido_rag
          │                         │
          │                    POST /buscar
          │                         │
          │                    ┌────┴────┐
          │                    │   EC2   │  FastAPI (puerto 8000)
          │                    │  (RAG)  │  Qdrant (puerto 6333)
          │                    └────┬────┘
          │                         │ fragmentos + fuentes
          │                         ▼
          │                  2ª llamada Groq
          │                  (genera respuesta)
          │                         │
          └─────────────────────────┘
                     │
                     ▼
             ┌───────────────┐
             │   DynamoDB    │  PK: tenantId#consultaId
             │ (TriageTable) │  GSI: por-estado (tenantId#estado)
             └───────┬───────┘
                     │ respondido_rag / enrutado
                     ▼
             ┌───────────────┐
             │    Resend     │  Correo al remitente (fire-and-forget)
             │  (API email)  │  respuesta RAG / acuse de enrutado
             └───────────────┘
```

## Decisiones de diseño

### ¿Por qué EventBridge entre S3 y SQS?
El fan-out emite eventos de dominio (`consulta.recibida`) en lugar de escribir directo a SQS. Esto permite en el futuro agregar más consumidores (analytics, notificaciones) sin cambiar el productor.

### ¿Por qué reservedConcurrency: 1?
Para la demo: hace visible que los mensajes se procesan secuencialmente (se ve en el frontend). Protege el rate limit de Groq (30 req/min free tier). En producción se sube a N para paralelismo.

### ¿Por qué el RAG en una EC2 y no como Lambda?
Los modelos de embedding (sentence-transformers all-MiniLM-L6-v2, ~90MB) y Qdrant requieren estado persistente y memoria estable. Una Lambda tiene cold start y límite de ~512MB en /tmp. La EC2 t3.medium es la excepción justificada; todo lo demás es serverless.

### ¿Por qué embeddings locales y no una API externa?
- Sin costo adicional ni dependencia de API key para el retrieval.
- Consistencia garantizada entre poblar (seeder) y consultar (retrieval): mismo modelo exacto.
- Funciona offline una vez que el modelo está en el contenedor.

### ¿Por qué Resend y no SES para los correos?
En el Learner Lab, SES suele estar en sandbox y el `LabRole` no garantiza permiso
`ses:SendEmail`. Resend es una API externa (mismo patrón que Groq: key en `.env`),
sin dependencia de permisos AWS. El envío es **fire-and-forget**: si Resend rechaza
el destinatario (típico en sandbox, solo acepta el correo de la cuenta), se loguea y
el worker sigue. El correo nunca bloquea el procesamiento; la consulta siempre queda
en DynamoDB. Solo `respondido_rag` y `enrutado` notifican; `no_aplica` y `fallido` no.

### Política de errores del worker
- **Input inválido** (texto vacío/null): detectado al inicio, `estado=fallido`, SQS elimina el mensaje. Sin reintento.
- **Error de sistema** (429, 401, 500, timeout, red): raise exception → SQS reintenta → DLQ tras 5 intentos.
- La DLQ en el flujo normal permanece vacía.

### Alarma de la DLQ (observabilidad)
Una CloudWatch Alarm vigila la métrica `ApproximateNumberOfMessagesVisible` de la DLQ
con umbral ≥ 1: apenas cae un mensaje, pasa a `ALARM` y notifica por correo vía SNS.
Dispara **una vez por incidente** (en la transición OK→ALARM), no por cada mensaje, así
que no genera spam. Como el LLM es de pago por request y el clasificador es confiable,
un mensaje en la DLQ siempre significa un fallo de sistema que el responsable debe
investigar y reprocesar (redrive), no una consulta inválida.

### ¿Por qué llama-3.1-8b-instant?
El free tier de Groq limita los tokens por día **por modelo** (100k en el 70b). El 8b
tiene un pool propio y más holgado, y consume menos tokens por consulta. Para la demo
prioriza disponibilidad sobre la calidad marginal del 70b; el modelo se cambia en una
constante de `worker.py` sin tocar el resto.
