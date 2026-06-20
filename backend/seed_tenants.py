#!/usr/bin/env python3
"""Inicializa los tenants en DynamoDB desde data/tenants.json.

Uso:
    python seed_tenants.py            # stage dev por defecto
    python seed_tenants.py --stage prod

Usa las credentials de ~/.aws (las mismas del Learner Lab).
Idempotente: vuelve a correrlo y solo actualiza, no duplica.
"""
import argparse
import json
from pathlib import Path

import boto3

TENANTS_FILE = Path(__file__).resolve().parent.parent / "data" / "tenants.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="dev", help="stage del deploy (default: dev)")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    table_name = f"hack-utec-triage-{args.stage}"
    tenants = json.loads(TENANTS_FILE.read_text(encoding="utf-8"))

    table = boto3.resource("dynamodb", region_name=args.region).Table(table_name)

    for t in tenants:
        table.put_item(
            Item={
                "pk": f"{t['tenantId']}#config",
                "sk": "CONFIG",
                "tenantId": t["tenantId"],
                "nombre": t["nombre"],
                "areas": t["areas"],
            }
        )
        print(f"  ✓ {t['tenantId']} ({t['nombre']}) — {len(t['areas'])} areas")

    print(f"\nListo: {len(tenants)} tenants en {table_name}")


if __name__ == "__main__":
    main()
