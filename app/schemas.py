"""Formatos de entrada e saída da API (validados pelo Pydantic)."""

from pydantic import BaseModel, Field


class RespostaUpload(BaseModel):
    """O que a API devolve depois de indexar um PDF."""

    arquivo: str
    trechos: int


class Pergunta(BaseModel):
    # Se o limite não for respeitado, o FastAPI devolve 422 sozinho, antes de rodar a rota.
    # 500 caracteres evita prompts gigantes (custo e abuso).
    pergunta: str = Field(min_length=5, max_length=500)


class RespostaPergunta(BaseModel):
    resposta: str
    paginas: list[int]
