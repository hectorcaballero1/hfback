import json
import os
import uuid
import boto3

s3 = boto3.client('s3')
events = boto3.client('events')

EVENT_BUS_NAME = os.environ['EVENT_BUS_NAME']


def handler(event, context):
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']

        response = s3.get_object(Bucket=bucket, Key=key)
        body = json.loads(response['Body'].read())

        tenant_id = body['tenantId']
        consultas = body.get('consultas', [])

        entries = []
        for consulta in consultas:
            entry = {
                'EventBusName': EVENT_BUS_NAME,
                'Source': 'hack-utec.fanout',
                'DetailType': 'consulta.recibida',
                'Detail': json.dumps({
                    'tenantId': tenant_id,
                    'consultaId': consulta.get('id', str(uuid.uuid4())),
                    'texto': consulta.get('texto'),
                    'remitente': consulta.get('remitente', ''),
                    'timestamp': consulta.get('timestamp', ''),
                }),
            }
            entries.append(entry)

        # EventBridge acepta hasta 10 entradas por llamada
        for i in range(0, len(entries), 10):
            batch = entries[i:i + 10]
            result = events.put_events(Entries=batch)
            if result.get('FailedEntryCount', 0) > 0:
                print(f"[fanout] Falló envío de {result['FailedEntryCount']} eventos")

    print(f"[fanout] Procesado {len(consultas)} consultas del tenant {tenant_id}")
