"""Guarda os trechos no banco vetorial (Qdrant) e busca os mais parecidos."""

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.documentos import Trecho
from app.ia import ProvedorIA

COLECAO = "edital"


class BaseDeConhecimento:
    def __init__(self, ia: ProvedorIA) -> None:
        self.ia = ia
        # ":memory:" roda o Qdrant dentro do próprio processo, sem servidor.
        # Os dados somem ao reiniciar a API (aceitável para um portfólio).
        self.qdrant = QdrantClient(":memory:")

    def tem_documento(self) -> bool:
        return self.qdrant.collection_exists(COLECAO)

    def indexar(self, trechos: list[Trecho]) -> int:
        """Apaga o edital anterior e guarda os novos trechos. Um edital por vez, para simplificar."""
        if self.tem_documento():
            self.qdrant.delete_collection(COLECAO)
        self.qdrant.create_collection(
            COLECAO,
            # COSINE: compara a "direção" dos vetores, ou seja, o assunto do texto,
            # e não o tamanho dele.
            vectors_config=VectorParams(size=self.ia.dimensao, distance=Distance.COSINE),
        )
        pontos = [
            PointStruct(
                id=numero,
                vector=self.ia.gerar_embedding(trecho.texto),
                # payload = dados extras guardados junto do vetor, devolvidos na busca
                payload={"texto": trecho.texto, "pagina": trecho.pagina},
            )
            for numero, trecho in enumerate(trechos)
        ]
        self.qdrant.upsert(COLECAO, points=pontos)
        return len(pontos)

    def buscar(self, pergunta: str, limite: int = 4) -> list[Trecho]:
        """Gera o embedding da pergunta e devolve os trechos mais próximos dele."""
        resultado = self.qdrant.query_points(
            COLECAO, query=self.ia.gerar_embedding(pergunta), limit=limite
        )
        return [Trecho(p.payload["texto"], p.payload["pagina"]) for p in resultado.points]
