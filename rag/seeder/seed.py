import hashlib
import os
import time
from pathlib import Path

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

QDRANT_URL = os.environ.get('QDRANT_URL', 'http://localhost:6333')
COLLECTION_NAME = os.environ.get('COLLECTION_NAME', 'triage_docs')
CORPUS_PATH = os.environ.get('CORPUS_PATH', '/corpus')
MODEL_NAME = 'all-MiniLM-L6-v2'
VECTOR_SIZE = 384
CHUNK_SIZE = 500      # caracteres aprox por chunk
CHUNK_OVERLAP = 80


def wait_for_qdrant(client, retries=15, delay=3):
    for i in range(retries):
        try:
            client.get_collections()
            print('[seeder] Qdrant disponible')
            return
        except Exception:
            print(f'[seeder] Esperando Qdrant... ({i+1}/{retries})')
            time.sleep(delay)
    raise RuntimeError('Qdrant no disponible tras esperar')


def ensure_collection(client):
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        print(f'[seeder] Colección {COLLECTION_NAME} creada')
    else:
        print(f'[seeder] Colección {COLLECTION_NAME} ya existe')


def chunk_text(text):
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    chunks = []
    current = ''

    for para in paragraphs:
        if len(current) + len(para) <= CHUNK_SIZE:
            current = (current + '\n\n' + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            # Si el párrafo solo ya excede el chunk, partirlo
            if len(para) > CHUNK_SIZE:
                for i in range(0, len(para), CHUNK_SIZE - CHUNK_OVERLAP):
                    chunks.append(para[i:i + CHUNK_SIZE])
            else:
                current = para

    if current:
        chunks.append(current)

    return chunks


def stable_id(tenant_id, fuente, chunk_index):
    raw = f"{tenant_id}|{fuente}|{chunk_index}"
    return int(hashlib.md5(raw.encode()).hexdigest()[:16], 16) % (10**15)


def seed_tenant(client, model, tenant_id, tenant_path):
    print(f'[seeder] Procesando tenant: {tenant_id}')
    txt_files = list(tenant_path.glob('*.txt')) + list(tenant_path.glob('*.md'))

    points = []
    for filepath in txt_files:
        fuente = filepath.name
        text = filepath.read_text(encoding='utf-8')
        chunks = chunk_text(text)
        print(f'  {fuente}: {len(chunks)} chunks')

        for idx, chunk in enumerate(chunks):
            embedding = model.encode(chunk).tolist()
            point_id = stable_id(tenant_id, fuente, idx)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        'tenantId': tenant_id,
                        'fuente': fuente,
                        'chunk_index': idx,
                        'texto': chunk,
                    },
                )
            )

    if points:
        # upsert garantiza idempotencia: mismo id = actualiza en lugar de duplicar
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        print(f'  → {len(points)} vectores insertados/actualizados para {tenant_id}')


def main():
    print('[seeder] Iniciando...')
    client = QdrantClient(url=QDRANT_URL)
    wait_for_qdrant(client)
    ensure_collection(client)

    model = SentenceTransformer(MODEL_NAME)

    corpus_root = Path(CORPUS_PATH)
    tenant_dirs = [d for d in corpus_root.iterdir() if d.is_dir()]

    if not tenant_dirs:
        print(f'[seeder] No se encontraron tenants en {CORPUS_PATH}')
        return

    for tenant_path in tenant_dirs:
        seed_tenant(client, model, tenant_path.name, tenant_path)

    print('[seeder] Completado.')


if __name__ == '__main__':
    main()
