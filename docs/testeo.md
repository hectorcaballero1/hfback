# Guía de testeo — HACK//UTEC

Flujo de prueba para validar el sistema end-to-end y para grabar la demo. El mismo
orden aplica a los dos tenants (UTEC y Banco Nacional).

## Antes de empezar

- [ ] Backend desplegado (`serverless deploy`) con el worker en `llama-3.1-8b-instant`
- [ ] EC2 del RAG levantada, con `qdrant` + `retrieval` y el seed inicial cargado
- [ ] Tenants sembrados (`python seed_tenants.py`) — `GET /tenants` responde
- [ ] Front corriendo con `VITE_API_URL` apuntando a la API
- [ ] Colas limpias (purgar `hack-utec-queue-dev` y `hack-utec-dlq-dev` si quedaron mensajes viejos)

> **Cuidá la cuota de Groq:** el free tier da 100.000 tokens/día por modelo. No subas
> cientos de consultas repetidas. El flujo de abajo usa ~12 consultas por tenant.

---

## Flujo por tenant

Seleccioná el tenant en el header antes de cada subida. Los JSON van en `data/`.

### Paso 1 — Consultas base (muestra los 3 veredictos)

Subí `consultas_base_<tenant>.json` (modo **Consultas**). Son 5 consultas **sin `id`**
(el backend genera el UUID solo). Andá a **En vivo** y mirá cómo se procesan:

| | UTEC | Banco |
|---|---|---|
| respondido_rag | constancia de estudios · apelación de nota | bloqueo de tarjeta · abrir cuenta |
| enrutado | pensión no registrada (tesorería) · bienestar | cargo no reconocido (fraudes) · estado de préstamo (créditos) |
| no_aplica | spam "gana dinero" | phishing "ganaste un premio" |

### Paso 2 — Subir corpus en caliente (modo Documentos)

Subí `corpus_<tenant>.json` (modo **Documentos**). Ingesta un dato puntual que **no
estaba** en el seed inicial:

- UTEC → `examenes_rezagados.txt`: "examen de rezagados cuesta 50 soles, igual para todos los cursos"
- Banco → `reposicion_tarjetas.txt`: "reposición de tarjeta cuesta 20 soles, igual para débito y crédito"

### Paso 3 — La consulta estrella (RAG responde con lo recién subido)

Subí `consulta_rag_<tenant>.json` (modo **Consultas**). Es 1 consulta que pregunta
justo por el dato del paso 2:

- UTEC → "¿cuál es el costo del examen de rezagados y si es el mismo para todos los cursos?"
- Banco → "¿cuánto cuesta la reposición de mi tarjeta y si es lo mismo para débito y crédito?"

**Resultado esperado:** veredicto `respondido_rag`, con la respuesta citando la fuente
(`examenes_rezagados.txt` / `reposicion_tarjetas.txt`). Esto demuestra que el dato se
ingestó **en caliente** y el sistema ya lo usa, sin reconstruir nada.

---

## Demostrar el correo (opcional)

Para que te llegue el email en el video, editá el `remitente` de la consulta estrella
(y/o de una enrutada) y poné **tu correo de la cuenta Resend**. El sandbox solo entrega
a ese correo; el resto los rechaza sin romper nada.

## Carga masiva (opcional, para llenar el dashboard)

`consultas_test_<tenant>.json` tiene 50 consultas cada uno (con mezcla de veredictos y
casos cruzados banco↔utec que caen en `no_aplica`). Útil para que "En vivo" y los
contadores se vean cargados. Ojo con la cuota de Groq si lo corrés varias veces.

---

## Qué mirar en cada vista

- **En vivo:** contadores por estado, avisos de transición y feed mientras drena la cola.
- **Consultas (registro):** tabla filtrable por veredicto; clic en una fila abre el
  detalle. En las `respondido_rag` se ve pregunta → respuesta → fuente.
- **Corpus:** confirmación de documentos enviados al RAG.

## Si algo cae en `fallido` o a la DLQ

- `fallido` en el dashboard = input inválido (texto vacío). Es esperado y auditable.
- Mensajes en la **DLQ** = fallo de sistema (típicamente Groq sin cuota / 429). No es
  un error de clasificación. Ver `arquitectura.md` para el detalle del ciclo de errores.

---

## Forzar un mensaje a la DLQ (para demostrar la alarma)

> **Mandar 50 mensajes NO sirve:** consultas válidas se resuelven bien y solo llenan la
> cola. La DLQ solo recibe mensajes por **fallo de sistema**. Para provocar uno de forma
> controlada, hacemos que el worker falle a propósito con una API key inválida.

1. En `backend/.env`, romper la key de Groq a propósito:
   ```
   GROQ_API_KEY=gsk_invalida
   ```
2. En `serverless.yml`, bajar temporalmente los tiempos para que caiga rápido:
   ```yaml
   functions:
     worker:
       timeout: 30          # antes 60 (debe ser <= VisibilityTimeout de la cola)
   # ...
   TriageQueue:
     VisibilityTimeout: 30  # antes 360
     RedrivePolicy:
       maxReceiveCount: 3   # antes 5: cae a la DLQ tras 3 fallos
   ```
   > `VisibilityTimeout` no puede ser menor que el `timeout` del worker, por eso se
   > bajan los dos a 30. El `401` de Groq vuelve al instante, así que 30s sobra.
3. Desplegar y subir **1** consulta válida (cualquiera de las base):
   ```bash
   serverless deploy
   ```
4. El worker recibe `401` de Groq → lanza excepción → SQS la reintenta. Con
   `maxReceiveCount: 3` y `VisibilityTimeout: 30`, tras 3 fallos (~90 s) el mensaje
   **cae a la DLQ**.
5. La métrica de la DLQ pasa a ≥1 → la **alarma de CloudWatch** entra en `ALARM` y
   dispara el correo (SNS) en unos minutos.
6. **Revertir todo:** restaurar la `GROQ_API_KEY` real, volver `worker.timeout: 60`,
   `VisibilityTimeout: 360`, `maxReceiveCount: 5`, `serverless deploy`, y purgar la DLQ:
   ```bash
   aws sqs purge-queue --queue-url $(aws sqs get-queue-url --queue-name hack-utec-dlq-dev --query QueueUrl --output text)
   ```

> Si no querés tocar nada en vivo: mostrá la alarma ya creada en la consola de
> CloudWatch y explicá el mecanismo. Es igual de válido para la presentación.
