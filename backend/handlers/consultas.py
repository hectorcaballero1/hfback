import base64
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


def _item_to_dict(item):
    return {
        'consultaId': item.get('consultaId'),
        'tenantId': item.get('tenantId'),
        'texto': item.get('texto'),
        'remitente': item.get('remitente'),
        'estado': item.get('estado'),
        'veredicto': item.get('veredicto'),
        'area': item.get('area'),
        'respuesta': item.get('respuesta'),
        'fuente': item.get('fuente'),
        'motivo': item.get('motivo'),
        'modelo': item.get('modelo'),
        'confianza': item.get('confianza'),
        'reintentos': item.get('reintentos', 0),
        'timestamp': item.get('timestamp'),
        'updatedAt': item.get('updatedAt'),
    }


def list_handler(event, context):
    try:
        params = event.get('queryStringParameters') or {}
        tenant_id = params.get('tenantId', '').strip()
        if not tenant_id:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'tenantId requerido'}),
            }

        estado = params.get('estado', 'resuelto')
        veredicto_filter = params.get('veredicto')
        limit = min(int(params.get('limit', 20)), 100)
        cursor = params.get('cursor')

        table = dynamo.Table(TABLE_NAME)
        gsi1pk = f"{tenant_id}#{estado}"

        query_kwargs = {
            'IndexName': 'por-estado',
            'KeyConditionExpression': Key('gsi1pk').eq(gsi1pk),
            'Limit': limit,
            'ScanIndexForward': False,
        }

        if veredicto_filter:
            query_kwargs['FilterExpression'] = 'veredicto = :v'
            query_kwargs['ExpressionAttributeValues'] = {':v': veredicto_filter}

        if cursor:
            try:
                last_key = json.loads(base64.b64decode(cursor).decode())
                query_kwargs['ExclusiveStartKey'] = last_key
            except Exception:
                pass

        resp = table.query(**query_kwargs)
        items = [_item_to_dict(i) for i in resp.get('Items', [])]

        next_cursor = None
        if 'LastEvaluatedKey' in resp:
            next_cursor = base64.b64encode(
                json.dumps(resp['LastEvaluatedKey']).encode()
            ).decode()

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({
                'items': items,
                'nextCursor': next_cursor,
                'count': len(items),
            }),
        }
    except Exception as e:
        print(f"[consultas/list] Error: {e}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'error_interno'}),
        }


def get_handler(event, context):
    try:
        params = event.get('queryStringParameters') or {}
        tenant_id = params.get('tenantId', '').strip()
        consulta_id = event.get('pathParameters', {}).get('id', '').strip()

        if not tenant_id or not consulta_id:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'tenantId y id requeridos'}),
            }

        table = dynamo.Table(TABLE_NAME)
        resp = table.get_item(
            Key={'pk': f"{tenant_id}#{consulta_id}", 'sk': 'MSG'}
        )
        item = resp.get('Item')
        if not item:
            return {
                'statusCode': 404,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'not_found'}),
            }

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps(_item_to_dict(item)),
        }
    except Exception as e:
        print(f"[consultas/get] Error: {e}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'error_interno'}),
        }
