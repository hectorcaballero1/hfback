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
                         │ s3:ObjectCreated
                         ▼
                  ┌─────────────┐
                  │ fanout.py   │  Lee JSON, emite 1 evento por consulta
                  │  (Lambda)   │
                  └──────┬──────┘
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

### Política de errores del worker
- **Input inválido** (texto vacío/null): detectado al inicio, `estado=fallido`, SQS elimina el mensaje. Sin reintento.
- **Error de sistema** (429, 401, 500, timeout, red): raise exception → SQS reintenta → DLQ tras 5 intentos.
- La DLQ en el flujo normal permanece vacía.
