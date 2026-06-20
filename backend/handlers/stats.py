import json
import os
import boto3
from boto3.dynamodb.conditions import Key

dynamo = boto3.resource('dynamodb')
TABLE_NAME = os.environ['TABLE_NAME']

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
}

ESTADOS = ['pendiente', 'procesando', 'resuelto', 'fallido']
VEREDICTOS = ['respondido_rag', 'enrutado', 'no_aplica']


def handler(event, context):
    try:
        params = event.get('queryStringParameters') or {}
        tenant_id = params.get('tenantId', '').strip()
        if not tenant_id:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'tenantId requerido'}),
            }

        table = dynamo.Table(TABLE_NAME)
        estados = {}
        veredictos = {v: 0 for v in VEREDICTOS}
        total = 0

        for estado in ESTADOS:
            gsi1pk = f"{tenant_id}#{estado}"
            resp = table.query(
                IndexName='por-estado',
                KeyConditionExpression=Key('gsi1pk').eq(gsi1pk),
                Select='COUNT',
            )
            count = resp.get('Count', 0)
            estados[estado] = count
            total += count

            # Contar veredictos solo para resueltos
            if estado == 'resuelto':
                for v in VEREDICTOS:
                    resp_v = table.query(
                        IndexName='por-estado',
                        KeyConditionExpression=Key('gsi1pk').eq(gsi1pk),
                        FilterExpression='veredicto = :v',
                        ExpressionAttributeValues={':v': v},
                        Select='COUNT',
                    )
                    veredictos[v] = resp_v.get('Count', 0)

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({
                'tenantId': tenant_id,
                'estados': estados,
                'veredictos': veredictos,
                'total': total,
            }),
        }
    except Exception as e:
        print(f"[stats] Error: {e}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'error_interno'}),
        }
