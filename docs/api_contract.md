# Contrato de API — Sistema de Triage HACK//UTEC

Base URL: `https://{api-id}.execute-api.us-east-1.amazonaws.com/dev`

> Todos los endpoints retornan `Content-Type: application/json` y headers CORS (`Access-Control-Allow-Origin: *`).

---

## Flujo de uso del frontend

```
1. GET /tenants                          → obtener lista de tenants para el selector
2. POST /uploads/presign {tenantId}      → obtener URL firmada de S3
3. PUT {uploadUrl} (directo a S3)        → subir el JSON de consultas
4. polling GET /stats?tenantId=X         → ver contadores actualizando en tiempo real
5. GET /consultas?tenantId=X&estado=...  → listar mensajes procesados
6. GET /consultas/{id}?tenantId=X        → ver detalle de un mensaje
```

---

## Endpoints

### GET /tenants
Lista los tenants disponibles para el selector del dashboard.

**Response 200:**
```json
{
  "tenants": [
    { "tenantId": "utec", "nombre": "UTEC" },
    { "tenantId": "banco", "nombre": "Banco Nacional" }
  ]
}
```

---

### POST /uploads/presign
Genera una URL prefirmada de S3 para que el frontend suba el JSON directamente.

**Body:**
```json
{ "tenantId": "utec", "tipo": "consultas" }
```
- `tipo` (opcional, default `consultas`): `consultas` para el flujo de triage,
  `documentos` para subir corpus al RAG. Decide el prefijo del objeto en S3 y, por
  ende, qué Lambda lo procesa.

**Response 200:**
```json
{
  "uploadUrl": "https://s3.amazonaws.com/hack-utec-uploads-dev-XXXX/consultas/utec/2026-06-20/abc.json?X-Amz-...",
  "key": "consultas/utec/2026-06-20/abc123.json"
}
```

Prefijos resultantes:
- `tipo=consultas`  → `consultas/{tenant}/...` → dispara `fanOut` (triage)
- `tipo=documentos` → `corpus/{tenant}/...`    → dispara `ragIngest` (corpus del RAG)

**Cómo usar la URL (PUT directo a S3):**
```
PUT {uploadUrl}
Content-Type: application/json
Body: { "tenantId": "utec", "consultas": [...] }
```
La URL expira en 5 minutos. No enviar el body a tu backend; ir directo a S3.

---

### GET /stats?tenantId=utec
Contadores por estado y veredicto. Diseñado para polling liviano (cada 2-5s).

**Query params:**
- `tenantId` (requerido)

**Response 200:**
```json
{
  "tenantId": "utec",
  "estados": {
    "pendiente": 0,
    "procesando": 1,
    "resuelto": 12,
    "fallido": 2
  },
  "veredictos": {
    "respondido_rag": 5,
    "enrutado": 6,
    "no_aplica": 1
  },
  "total": 15
}
```

---

### GET /consultas?tenantId=utec&estado=resuelto&limit=20&cursor=...
Lista paginada de consultas filtrando por estado y/o veredicto.

**Query params:**
- `tenantId` (requerido)
- `estado`: `pendiente` | `procesando` | `resuelto` | `fallido` (default: `resuelto`)
- `veredicto`: `respondido_rag` | `enrutado` | `no_aplica` (opcional, filtra dentro del estado)
- `limit`: número de resultados (default: 20, máximo: 100)
- `cursor`: token de paginación (tomar del campo `nextCursor` de la respuesta anterior)

**Response 200:**
```json
{
  "items": [
    {
      "consultaId": "u-001",
      "tenantId": "utec",
      "texto": "¿Cuándo es el período de matrícula?",
      "remitente": "ana@utec.edu.pe",
      "estado": "resuelto",
      "veredicto": "respondido_rag",
      "area": null,
      "respuesta": "El período de matrícula regular es del 1 al 15 de julio de 2025 [reglamento_academico.txt]",
      "fuente": "reglamento_academico.txt",
      "motivo": null,
      "modelo": "groq",
      "confianza": "0.92",
      "reintentos": 0,
      "timestamp": "2026-06-20T10:00:00Z",
      "updatedAt": "2026-06-20T10:00:08Z"
    }
  ],
  "nextCursor": "eyJwayI6InV0...",
  "count": 1
}
```

**Notas:**
- Ordenado por timestamp descendente (más recientes primero).
- `area` solo tiene valor cuando `veredicto = "enrutado"`.
- `respuesta` y `fuente` solo tienen valor cuando `veredicto = "respondido_rag"`.
- `motivo` solo tiene valor cuando `estado = "fallido"` (ej: `"texto_invalido"`).
- `nextCursor` es `null` cuando no hay más páginas.

---

### GET /consultas/{id}?tenantId=utec
Detalle completo de una consulta.

**Path params:**
- `id`: el `consultaId` del mensaje

**Query params:**
- `tenantId` (requerido)

**Response 200:** objeto con los mismos campos que los items de `/consultas`

**Response 404:**
```json
{ "error": "not_found" }
```

---

## Formato del JSON de consultas (tipo=consultas, para subir a S3)

```json
{
  "tenantId": "utec",
  "consultas": [
    {
      "id": "c-001",
      "texto": "¿Cuándo es el período de matrícula?",
      "remitente": "usuario@email.com",
      "timestamp": "2026-06-20T10:00:00Z"
    }
  ]
}
```

## Formato del JSON de corpus (tipo=documentos, para subir a S3)

Para alimentar el RAG de un tenant en caliente. Tras el PUT, `ragIngest` reenvía
cada documento a `POST {RAG_URL}/documentos`.

```json
{
  "tenantId": "utec",
  "documentos": [
    {
      "fuente": "calendario_2026.txt",
      "texto": "El semestre 2026-1 inicia el 10 de marzo. Las matrículas..."
    }
  ]
}
```

- `fuente`: nombre/identificador del documento. Re-subir la misma `fuente` actualiza
  (idempotente por tenantId+fuente+chunk), no duplica.
- `texto`: contenido en texto libre; el RAG lo chunkea y embebe.

- `id`: identificador único de la consulta (string). Si se omite, el sistema genera uno aleatorio.
- `texto`: el mensaje en texto libre (requerido). Si es vacío o null, el mensaje queda en estado `fallido`.
- `remitente`: email o identificador del remitente (opcional).
- `timestamp`: ISO 8601 UTC (opcional; si se omite, se usa el timestamp de recepción).

---

## Estados del ciclo de vida de un mensaje

```
pendiente → procesando → resuelto
                      ↘ fallido   (input inválido o error permanente)
```

- `pendiente`: recibido, esperando en cola.
- `procesando`: worker lo está procesando actualmente.
- `resuelto`: procesado exitosamente; tiene `veredicto` asignado.
- `fallido`: error no recuperable (texto vacío, error permanente).

---

## Veredictos posibles

| Veredicto | Significado | Campos extra en el item |
|---|---|---|
| `respondido_rag` | Respondido con documentos del tenant | `respuesta`, `fuente` |
| `enrutado` | Derivado a área humana | `area` |
| `no_aplica` | Spam o fuera de alcance | — |
