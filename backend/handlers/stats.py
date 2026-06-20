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


def _count(table, gsi1pk, veredicto=None):
    """Cuenta TODOS los ítems del GSI paginando.

    Con Select='COUNT' DynamoDB solo cuenta lo escaneado en cada página (límite de
    1 MB) y devuelve LastEvaluatedKey si falta. Sin este bucle el conteo se queda
    corto cuando los ítems son grandes (texto/respuesta largos).
    """
    total = 0
    kwargs = {
        'IndexName': 'por-estado',
        'KeyConditionExpression': Key('gsi1pk').eq(gsi1pk),
        'Select': 'COUNT',
    }
    if veredicto:
        kwargs['FilterExpression'] = 'veredicto = :v'
        kwargs['ExpressionAttributeValues'] = {':v': veredicto}
    while True:
        resp = table.query(**kwargs)
        total += resp.get('Count', 0)
        last_key = resp.get('LastEvaluatedKey')
        if not last_key:
            return total
        kwargs['ExclusiveStartKey'] = last_key


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
            count = _count(table, gsi1pk)
            estados[estado] = count
            total += count

            # Contar veredictos solo para resueltos
            if estado == 'resuelto':
                for v in VEREDICTOS:
                    veredictos[v] = _count(table, gsi1pk, v)

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
