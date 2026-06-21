import json
import os
import re
import requests
from datetime import datetime, timezone
import boto3
from boto3.dynamodb.conditions import Key

dynamo = boto3.resource('dynamodb')
TABLE_NAME = os.environ['TABLE_NAME']
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
RAG_URL = os.environ.get('RAG_URL', '')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
# `or` y no get(default): si EMAIL_FROM viene como cadena vacía desde el .env,
# igual cae al remitente de prueba de Resend (si no, Resend da 422 "domain invalid").
EMAIL_FROM = os.environ.get('EMAIL_FROM') or 'onboarding@resend.dev'
# Umbral de similitud (cosine 0-1) para aceptar una respuesta del RAG. Por debajo,
# se considera que no hay respuesta documentada y se degrada a enrutado.
RAG_SCORE_MIN = 0.3

GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
GROQ_MODEL = 'llama-3.1-8b-instant'
RESEND_URL = 'https://api.resend.com/emails'

# TODO: áreas válidas por tenant — leer de DynamoDB config item
TENANT_CONFIG = {
    'utec': {
        'nombre': 'UTEC',
        'areas': ['admisiones', 'registro_academico', 'tesoreria', 'bienestar', 'sistemas'],
    },
    'banco': {
        'nombre': 'Banco Nacional',
        'areas': ['atencion_cliente', 'creditos', 'operaciones', 'fraudes', 'inversiones'],
    },
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _put_estado(table, tenant_id, consulta_id, estado, extra=None):
    pk = f"{tenant_id}#{consulta_id}"
    timestamp_original = extra.get('timestamp', _now_iso()) if extra else _now_iso()
    gsi1sk = f"{timestamp_original}#{consulta_id}"

    attrs = {
        'pk': pk,
        'sk': 'MSG',
        'tenantId': tenant_id,
        'consultaId': consulta_id,
        'gsi1pk': f"{tenant_id}#{estado}",
        'gsi1sk': gsi1sk,
        'estado': estado,
        'updatedAt': _now_iso(),
    }
    if extra:
        attrs.update(extra)

    table.put_item(Item=attrs)


def _enviar_email(destinatario, asunto, html):
    """Notificación fire-and-forget vía Resend.

    El sandbox de Resend solo acepta envíos al correo de la cuenta; cualquier otro
    destinatario es RECHAZADO (no ignorado). Por eso esto nunca lanza: loguea el
    rechazo/error y deja que el procesamiento siga. La consulta ya quedó en Dynamo.
    """
    if not RESEND_API_KEY or not destinatario:
        return
    try:
        resp = requests.post(
            RESEND_URL,
            headers={'Authorization': f'Bearer {RESEND_API_KEY}'},
            json={'from': EMAIL_FROM, 'to': [destinatario], 'subject': asunto, 'html': html},
            timeout=8,
        )
        if resp.status_code >= 400:
            print(f"[worker] Email rechazado para {destinatario}: {resp.status_code} {resp.text}")
        else:
            print(f"[worker] Email enviado a {destinatario}")
    except Exception as e:
        print(f"[worker] Error enviando email a {destinatario}: {e}")


def _call_groq(messages, timeout=25):
    resp = requests.post(
        GROQ_URL,
        headers={
            'Authorization': f'Bearer {GROQ_API_KEY}',
            'Content-Type': 'application/json',
        },
        json={
            'model': GROQ_MODEL,
            'messages': messages,
            'temperature': 0.1,
            'max_tokens': 512,
        },
        timeout=timeout,
    )

    if resp.status_code == 429:
        raise RuntimeError(f"groq_429: {resp.text}")
    if resp.status_code == 401:
        raise RuntimeError(f"groq_401: {resp.text}")
    if resp.status_code >= 500:
        raise RuntimeError(f"groq_{resp.status_code}: {resp.text}")
    resp.raise_for_status()

    return resp.json()['choices'][0]['message']['content']


def _clasificar(texto, tenant_id):
    config = TENANT_CONFIG.get(tenant_id, {'areas': ['general'], 'nombre': tenant_id})
    areas_str = ', '.join(config['areas'])

    # TODO: prompt de clasificación — ajustar tono y ejemplos por tenant
    prompt = f"""Eres un clasificador de consultas para {config['nombre']}.
Analiza el siguiente mensaje y decide UNA de estas acciones:

1. "respondido_rag" - Si la consulta puede responderse con documentos internos (reglamentos, FAQs, políticas).
2. "enrutado" - Si es un caso real que necesita atención humana. Identifica el área: {areas_str}.
3. "no_aplica" - Si es spam, prueba, o completamente irrelevante.

Responde SOLO con JSON válido, sin explicaciones:
{{"veredicto": "respondido_rag"|"enrutado"|"no_aplica", "area": "nombre_area_o_null", "confianza": 0.0-1.0}}

Mensaje: {texto}"""

    content = _call_groq([{'role': 'user', 'content': prompt}])

    # Extraer JSON de la respuesta (Groq a veces añade texto extra)
    match = re.search(r'\{[^}]+\}', content, re.DOTALL)
    if not match:
        raise ValueError(f"Respuesta de Groq no tiene JSON: {content}")

    result = json.loads(match.group())
    veredicto = result.get('veredicto', 'enrutado')
    if veredicto not in ('respondido_rag', 'enrutado', 'no_aplica'):
        veredicto = 'enrutado'

    return veredicto, result.get('area'), result.get('confianza', 0.8)


def _buscar_rag(texto, tenant_id):
    if not RAG_URL:
        return None

    try:
        resp = requests.post(
            f"{RAG_URL}/buscar",
            json={'texto': texto, 'tenantId': tenant_id, 'top_k': 3},
            timeout=8,  # 8s: primera llamada carga el modelo sentence-transformers
        )
        resp.raise_for_status()
        fragmentos = resp.json().get('fragmentos', [])

        # Umbral de similitud: si la mejor coincidencia es débil, NO hay respuesta
        # documentada real. Devolver vacío para que el worker degrade a enrutado en
        # vez de forzar a Groq a redactar sobre fragmentos irrelevantes.
        mejor = max((f.get('score', 0) for f in fragmentos), default=0)
        print(f"[worker] RAG mejor score={mejor:.3f} (umbral {RAG_SCORE_MIN})")
        if mejor < RAG_SCORE_MIN:
            return []
        return [f for f in fragmentos if f.get('score', 0) >= RAG_SCORE_MIN]
    except Exception as e:
        print(f"[worker] RAG no disponible: {e}")
        return None


def _generar_respuesta_rag(texto, fragmentos):
    contexto = '\n\n'.join(
        f"[{f['fuente']}]: {f['texto']}" for f in fragmentos
    )

    prompt = f"""Usa los siguientes fragmentos de documentación para responder la consulta.
Sé conciso y cita la fuente entre corchetes.

Fragmentos:
{contexto}

Consulta: {texto}

Respuesta:"""

    return _call_groq([{'role': 'user', 'content': prompt}])


def handler(event, context):
    table = dynamo.Table(TABLE_NAME)
    batch_item_failures = []

    for record in event['Records']:
        message_id = record['messageId']
        try:
            detail = json.loads(record['body'])
            # EventBridge envuelve el evento; el payload está en 'detail'
            if 'detail' in detail:
                detail = detail['detail']

            tenant_id = detail.get('tenantId', '')
            consulta_id = detail.get('consultaId', '')
            texto = detail.get('texto')
            remitente = detail.get('remitente', '')
            timestamp = detail.get('timestamp', _now_iso())

            # Validación de input: error de INPUT → fallido inmediato, sin reintento
            if not texto or not str(texto).strip():
                print(f"[worker] Input inválido: consultaId={consulta_id}")
                _put_estado(table, tenant_id, consulta_id, 'fallido', {
                    'texto': texto,
                    'remitente': remitente,
                    'timestamp': timestamp,
                    'motivo': 'texto_invalido',
                })
                continue  # Retornar éxito: SQS elimina el mensaje

            texto = str(texto).strip()

            # Marcar como procesando
            _put_estado(table, tenant_id, consulta_id, 'procesando', {
                'texto': texto,
                'remitente': remitente,
                'timestamp': timestamp,
            })

            # Clasificar con Groq
            # Errores de SISTEMA (429, 401, 500, red) lanzan exception → SQS reintenta
            veredicto, area, confianza = _clasificar(texto, tenant_id)

            extra = {
                'texto': texto,
                'remitente': remitente,
                'timestamp': timestamp,
                'veredicto': veredicto,
                'confianza': str(confianza),
                'modelo': 'groq',
            }

            if veredicto == 'respondido_rag':
                fragmentos = _buscar_rag(texto, tenant_id)
                if fragmentos:
                    respuesta = _generar_respuesta_rag(texto, fragmentos)
                    extra['respuesta'] = respuesta
                    extra['fuente'] = fragmentos[0].get('fuente', '')
                else:
                    # RAG no disponible: degradar a enrutado (no bloquear el flujo)
                    veredicto = 'enrutado'
                    extra['veredicto'] = 'enrutado'
                    area = TENANT_CONFIG.get(tenant_id, {}).get('areas', ['general'])[0]
                    extra['motivo'] = 'rag_no_disponible'

            if veredicto == 'enrutado':
                extra['area'] = area

            _put_estado(table, tenant_id, consulta_id, 'resuelto', extra)
            print(f"[worker] Resuelto: {tenant_id}#{consulta_id} → {veredicto}")

            # Notificación por correo (fire-and-forget; nunca rompe el procesamiento)
            if veredicto == 'respondido_rag':
                _enviar_email(
                    remitente,
                    'Respuesta a tu consulta',
                    f"<p>Hola,</p><p>Recibimos tu consulta:</p>"
                    f"<blockquote>{texto}</blockquote>"
                    f"<p><strong>Respuesta:</strong></p><p>{extra.get('respuesta', '')}</p>"
                    f"<p style='color:#6b6b6b;font-size:12px'>Fuente: {extra.get('fuente', '')}</p>",
                )
            elif veredicto == 'enrutado':
                _enviar_email(
                    remitente,
                    'Tu consulta fue derivada',
                    f"<p>Hola,</p><p>Tu consulta fue derivada al área "
                    f"<strong>{extra.get('area', '')}</strong> y será atendida por un especialista.</p>"
                    f"<blockquote>{texto}</blockquote>",
                )

        except Exception as e:
            # Error de SISTEMA: reportar falla para que SQS reintente este mensaje
            print(f"[worker] Error en mensaje {message_id}: {e}")
            batch_item_failures.append({'itemIdentifier': message_id})

    return {'batchItemFailures': batch_item_failures}
