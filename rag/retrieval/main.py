import hashlib
import os
from typing import Optional
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Filter,
    FieldCondition,
    MatchValue,
    PointStruct,
    Distance,
    VectorParams,
)

QDRANT_URL = os.environ.get('QDRANT_URL', 'http://localhost:6333')
COLLECTION_NAME = os.environ.get('COLLECTION_NAME', 'triage_docs')
MODEL_NAME = 'all-MiniLM-L6-v2'
VECTOR_SIZE = 384
CHUNK_SIZE = 500       # mismos valores que el seeder, para consistencia
CHUNK_OVERLAP = 80

app = FastAPI(title='RAG Retrieval Service')

# Carga del modelo al iniciar el servicio (no lazy)
model = SentenceTransformer(MODEL_NAME)
client = QdrantClient(url=QDRANT_URL)


def _ensure_collection():
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def _chunk_text(text):
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    chunks = []
    current = ''
    for para in paragraphs:
        if len(current) + len(para) <= CHUNK_SIZE:
            current = (current + '\n\n' + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) > CHUNK_SIZE:
                for i in range(0, len(para), CHUNK_SIZE - CHUNK_OVERLAP):
                    chunks.append(para[i:i + CHUNK_SIZE])
                current = ''
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks


def _stable_id(tenant_id, fuente, chunk_index):
    raw = f"{tenant_id}|{fuente}|{chunk_index}"
    return int(hashlib.md5(raw.encode()).hexdigest()[:16], 16) % (10**15)


class BuscarRequest(BaseModel):
    texto: str
    tenantId: str
    top_k: Optional[int] = 5


class DocumentoRequest(BaseModel):
    tenantId: str
    fuente: str            # nombre/identificador del documento (ej. "faq_v2.txt")
    texto: str             # contenido en texto libre


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


@app.post('/documentos')
def documentos(req: DocumentoRequest):
    """Ingesta texto al corpus de un tenant en caliente (sin re-seedear).

    Chunkea, embedda y hace upsert en Qdrant con el tenantId. Idempotente por
    (tenantId, fuente, chunk_index): re-subir la misma fuente actualiza, no duplica.
    """
    _ensure_collection()

    chunks = _chunk_text(req.texto)
    if not chunks:
        return {'ok': False, 'error': 'texto_vacio', 'chunks': 0}

    points = [
        PointStruct(
            id=_stable_id(req.tenantId, req.fuente, idx),
            vector=model.encode(chunk).tolist(),
            payload={
                'tenantId': req.tenantId,
                'fuente': req.fuente,
                'chunk_index': idx,
                'texto': chunk,
            },
        )
        for idx, chunk in enumerate(chunks)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points)

    return {'ok': True, 'tenantId': req.tenantId, 'fuente': req.fuente, 'chunks': len(points)}
