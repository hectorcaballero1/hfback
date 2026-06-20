# HACK//UTEC — Sistema de Triage Inteligente Multitenant

Sistema serverless de clasificación automática de consultas en texto libre. Un LLM (Groq) asigna un **veredicto** por mensaje: `respondido_rag`, `enrutado` o `no_aplica`. Demo con 2 tenants: UTEC (universidad) y Banco Nacional.

## Arquitectura

```
S3 → Lambda fan-out → EventBridge → SQS → Lambda worker (Groq) → DynamoDB
                                               ↕
                                          EC2 (RAG: Qdrant + FastAPI)
```

Ver diagrama completo en [docs/arquitectura.md](docs/arquitectura.md).

## Estructura

```
├── backend/          # Serverless Framework — serverless.yml + Lambda handlers
├── rag/              # Docker Compose — Qdrant + FastAPI retrieval + seeder
│   └── corpus/       # Documentos de cada tenant (txt/md)
├── data/             # JSON de consultas sintéticas para demo
└── docs/             # Contrato de API, manual de despliegue, guión de demo
```

## Despliegue rápido

1. **EC2 con RAG:** ver [docs/deploy_manual.md](docs/deploy_manual.md) — Parte 1
2. **Stack serverless:** ver [docs/deploy_manual.md](docs/deploy_manual.md) — Parte 2
3. **Contrato de API para el frontend:** [docs/api_contract.md](docs/api_contract.md)

## Variables de entorno requeridas

Copiar `.env.example` a `.env` y completar:
- `ACCOUNT_ID`: AWS Account ID del Learner Lab
- `GROQ_API_KEY`: API key de Groq (https://console.groq.com)
- `RAG_URL`: URL de la EC2 con el servicio de retrieval (ej: `http://1.2.3.4:8000`)

## Stack técnico

- **Backend:** Serverless Framework v4, Python 3.12, AWS Lambda
- **Mensajería:** S3, EventBridge, SQS (con DLQ)
- **Base de datos:** DynamoDB (tabla única, GSI por estado)
- **LLM:** Groq (llama-3.3-70b-versatile), fallback opcional a Gemini
- **RAG:** Qdrant + sentence-transformers all-MiniLM-L6-v2 (local, sin API externa)
- **Infra:** AWS Academy Learner Lab con LabRole
