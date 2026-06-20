import json
import os
import boto3
import requests

s3 = boto3.client('s3')
RAG_URL = os.environ.get('RAG_URL', '')


def handler(event, context):
    """Se dispara cuando el front sube un JSON de corpus a corpus/{tenant}/...
    Lee el documento y lo reenvía al RAG (POST /documentos) para ingestarlo.

    Formato esperado del JSON en S3:
      { "tenantId": "utec", "documentos": [ { "fuente": "x.txt", "texto": "..." } ] }
    """
    if not RAG_URL:
        print('[ragingest] RAG_URL no configurado; no se puede ingestar al RAG')
        return

    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        response = s3.get_object(Bucket=bucket, Key=key)
        body = json.loads(response['Body'].read())

        tenant_id = body.get('tenantId', '')
        documentos = body.get('documentos', [])

        ok, fail = 0, 0
        for doc in documentos:
            try:
                resp = requests.post(
                    f"{RAG_URL}/documentos",
                    json={
                        'tenantId': tenant_id,
                        'fuente': doc.get('fuente', 'sin_fuente'),
                        'texto': doc.get('texto', ''),
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                ok += 1
                print(f"[ragingest] {tenant_id}/{doc.get('fuente')}: {resp.json()}")
            except Exception as e:
                fail += 1
                print(f"[ragingest] Error ingestando {doc.get('fuente')}: {e}")

        print(f"[ragingest] tenant={tenant_id} ingestados={ok} fallidos={fail}")
