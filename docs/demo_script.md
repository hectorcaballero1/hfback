# Guión de Demo — HACK//UTEC Triage Inteligente (5 min)

## Antes de grabar: checklist

- [ ] EC2 con RAG levantada y warm-up hecho (`POST /buscar` de prueba ejecutado)
- [ ] Stack serverless deployado y URL de API en el frontend configurada
- [ ] Tenants inicializados en DynamoDB
- [ ] Frontend corriendo y apuntando a la API correcta
- [ ] Archivo `data/consultas_utec.json` listo para subir

---

## Guión (5 minutos)

### 0:00 – 0:30 | Contexto del problema

> "Las organizaciones reciben cientos de consultas al día por correo, formularios y canales digitales. Clasificarlas y derivarlas manualmente es lento y costoso. Nuestro sistema lo hace automáticamente, en tiempo real, para cualquier organización."

### 0:30 – 1:00 | Mostrar la arquitectura (diagrama)

Mencionar brevemente:
- Entrada: JSON de consultas → S3
- Fan-out serverless → EventBridge → SQS
- Worker con LLM (Groq) decide el veredicto
- Resultado en DynamoDB, frontend hace polling

### 1:00 – 2:00 | Demo UTEC — subir consultas y ver el pipeline en vivo

1. En el frontend: seleccionar tenant "UTEC"
2. Subir `data/consultas_utec.json` (10 consultas: mezcla de los 3 veredictos + 2 rotas)
3. Mostrar el contador de stats actualizando en tiempo real mientras el worker procesa
4. Señalar que `reservedConcurrency=1` hace que los mensajes se procesen de a uno (visible)

### 2:00 – 3:00 | Mostrar los 3 veredictos

- **respondido_rag** (u-001, u-007, u-008): "El sistema encontró la respuesta en el corpus documental de UTEC y la cita con su fuente"
- **enrutado** (u-002, u-006): "Este caso necesita un humano; el sistema identificó el área correcta: Registro Académico / Tesorería"
- **no_aplica** (u-004): "Spam detectado y apartado como baja prioridad"

### 3:00 – 3:30 | Demo Banco — cambiar de tenant

1. Seleccionar tenant "Banco Nacional"
2. Subir `data/consultas_banco.json`
3. Mostrar que el sistema usa áreas distintas para el banco (fraudes, créditos, etc.)
4. Destacar: **mismo pipeline, configuración por tenant**

### 3:30 – 4:00 | Mensajes inválidos y tolerancia a errores

Mostrar en el dashboard:
- u-009 y u-010 aparecen con `estado = fallido`, `motivo = texto_invalido`
- Explicar: "El worker los detecta al inicio, los registra como fallidos y los descarta. No se pierden — quedan auditables en la base de datos."

### 4:00 – 4:30 | DLQ y resiliencia

> "La arquitectura incluye una Dead Letter Queue. En el flujo normal permanece vacía porque el worker maneja los casos inválidos de forma explícita. La DLQ actúa como red de seguridad para fallos del sistema: si Groq se cae o hay un error de red, el mensaje se reintenta automáticamente hasta 5 veces antes de caer a la DLQ."

Mostrar la DLQ configurada en la consola de SQS.

### 4:30 – 5:00 | Cierre y escalabilidad

> "Con `reservedConcurrency: 1` procesamos de a uno para la demo. En producción, subir ese número a N procesa N mensajes en paralelo sin cambiar una línea de lógica. El sistema es multitenant, sin estado en la Lambda, y completamente serverless excepto el RAG que requiere un modelo local."

---

## Cómo demostrar la DLQ en vivo (opcional, si el jurado lo pide)

> **Tiempo estimado: ~2 minutos de configuración + ~30 segundos de espera**

1. En la consola SQS, editar la cola `hack-utec-queue-dev`:
   - Cambiar `visibilityTimeout` a **30 segundos**
   - Cambiar `maxReceiveCount` a **1**
2. En `.env`, cambiar `GROQ_API_KEY` a un valor inválido (ej: `gsk_INVALIDA`)
3. Re-deployar: `serverless deploy --stage dev`
4. Subir 1-2 consultas válidas
5. El worker falla con 401 (error de sistema → reintenta), y tras 1 reintento el mensaje cae a la DLQ en ~30 segundos
6. Mostrar el mensaje en la DLQ en la consola SQS
7. Revertir los cambios y re-deployar

**Alternativa sin reconfigurar:** mostrar en la consola SQS la DLQ configurada con sus parámetros (`maxReceiveCount: 5`, `messageRetentionPeriod: 24h`) y explicar el mecanismo al jurado. Es técnicamente equivalente para una presentación.
