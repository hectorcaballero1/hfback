import json
import os
import uuid
from datetime import datetime
import boto3

s3 = boto3.client('s3')
BUCKET_NAME = os.environ['BUCKET_NAME']

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
}


def handler(event, context):
    try:
        body = json.loads(event.get('body') or '{}')
        tenant_id = body.get('tenantId', '').strip()
        if not tenant_id:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'tenantId requerido'}),
            }

        # tipo decide el prefijo y, por ende, qué Lambda lo procesa:
        #   consultas  -> consultas/{tenant}/...  -> fanOut (flujo de triage)
        #   documentos -> corpus/{tenant}/...     -> ragIngest (corpus del RAG)
        tipo = body.get('tipo', 'consultas')
        prefijo = 'corpus' if tipo == 'documentos' else 'consultas'

        date_prefix = datetime.utcnow().strftime('%Y-%m-%d')
        key = f"{prefijo}/{tenant_id}/{date_prefix}/{uuid.uuid4()}.json"

        upload_url = s3.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': BUCKET_NAME,
                'Key': key,
                'ContentType': 'application/json',
            },
            ExpiresIn=300,
        )

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'uploadUrl': upload_url, 'key': key}),
        }
    except Exception as e:
        print(f"[presign] Error: {e}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'error_interno'}),
        }
