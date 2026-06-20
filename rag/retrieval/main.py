import os
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

QDRANT_URL = os.environ.get('QDRANT_URL', 'http://localhost:6333')
COLLECTION_NAME = os.environ.get('COLLECTION_NAME', 'triage_docs')
MODEL_NAME = 'all-MiniLM-L6-v2'

app = FastAPI(title='RAG Retrieval Service')

# Carga del modelo al iniciar el servicio (no lazy)
model = SentenceTransformer(MODEL_NAME)
client = QdrantClient(url=QDRANT_URL)


class BuscarRequest(BaseModel):
    texto: str
    tenantId: str
    top_k: Optional[int] = 5


@app.get('/health')
def health():
    return {'status': 'ok', 'model': MODEL_NAME}


@app.post('/buscar')
def buscar(req: BuscarRequest):
    embedding = model.encode(req.texto).tolist()

    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=embedding,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key='tenantId',
                    match=MatchValue(value=req.tenantId),
                )
            ]
        ),
        limit=req.top_k,
        with_payload=True,
    )

    fragmentos = [
        {
            'texto': hit.payload.get('texto', ''),
            'fuente': hit.payload.get('fuente', ''),
            'score': round(hit.score, 4),
        }
        for hit in results
    ]

    return {'fragmentos': fragmentos}
