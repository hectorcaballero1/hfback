import json
import os
import boto3
from boto3.dynamodb.conditions import Attr

dynamo = boto3.resource('dynamodb')
TABLE_NAME = os.environ['TABLE_NAME']

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
}


def handler(event, context):
    try:
        table = dynamo.Table(TABLE_NAME)

        # TODO: Scan aceptable solo por volumen mínimo de items CONFIG (N tenants).
        # En producción usar GSI o tabla separada para tenants; nunca Scan en tabla de mensajes.
        resp = table.scan(
            FilterExpression=Attr('sk').eq('CONFIG'),
            ProjectionExpression='tenantId, nombre',
        )

        tenants = [
            {'tenantId': item['tenantId'], 'nombre': item.get('nombre', item['tenantId'])}
            for item in resp.get('Items', [])
        ]

        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'tenants': tenants}),
        }
    except Exception as e:
        print(f"[tenants] Error: {e}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': 'error_interno'}),
        }
