"""Provedores de IA: o Gemini de verdade e um falso para rodar sem internet."""

import os
import re
import zlib
from abc import ABC, abstractmethod
from collections.abc import Iterator

from google import genai
from google.genai import types

from app.documentos import Trecho

MODELO_EMBEDDING = "gemini-embedding-001"
MODELO_LLM = "gemini-2.5-flash"  # rápido e barato; bom para respostas curtas

# Marcadores que separam as partes do prompt (a FakeIA usa para achar os trechos).
MARCA_TRECHOS = "TRECHOS DO EDITAL:"
MARCA_PERGUNTA = "PERGUNTA:"
NAO_ENCONTREI = "Não encontrei essa informação no edital"


class ProvedorIA(ABC):
    """Contrato que todo provedor precisa cumprir.

    O resto do sistema só conhece esta classe, nunca o Gemini diretamente.
    Assim dá para trocar de provedor (ou usar o falso nos testes) sem mexer no resto.
    """

    dimensao: int  # tamanho do vetor gerado; o Qdrant precisa saber disso

    @abstractmethod
    def gerar_embedding(self, texto: str) -> list[float]:
        """Transforma um texto num vetor de números que representa seu significado."""

    @abstractmethod
    def responder(self, prompt: str) -> str:
        """Envia o prompt ao LLM e devolve a resposta inteira de uma vez."""

    @abstractmethod
    def responder_stream(self, prompt: str) -> Iterator[str]:
        """Igual a responder, mas entrega a resposta em pedaços, conforme o LLM gera."""


class GeminiIA(ProvedorIA):
    dimensao = 768  # o modelo aceita vetores menores; 768 economiza memória

    def __init__(self, chave: str) -> None:
        self.cliente = genai.Client(api_key=chave)

    def gerar_embedding(self, texto: str) -> list[float]:
        resultado = self.cliente.models.embed_content(
            model=MODELO_EMBEDDING,
            contents=texto,
            config=types.EmbedContentConfig(output_dimensionality=self.dimensao),
        )
        return resultado.embeddings[0].values

    def responder(self, prompt: str) -> str:
        resposta = self.cliente.models.generate_content(
            model=MODELO_LLM,
            contents=prompt,
            # Temperatura baixa = respostas mais previsíveis e menos "criativas",
            # o que ajuda o modelo a não inventar informação.
            config=types.GenerateContentConfig(temperature=0.1),
        )
        return resposta.text or NAO_ENCONTREI

    def responder_stream(self, prompt: str) -> Iterator[str]:
        pedacos = self.cliente.models.generate_content_stream(
            model=MODELO_LLM,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        for pedaco in pedacos:
            if pedaco.text:  # alguns pedaços vêm sem texto (só metadados)
                yield pedaco.text


class FakeIA(ProvedorIA):
    """Imita a IA sem internet. Não entende significado, só compara palavras iguais."""

    dimensao = 256

    def gerar_embedding(self, texto: str) -> list[float]:
        # "Hashing trick": cada palavra cai numa posição fixa do vetor e soma 1 ali.
        # Textos com palavras em comum ficam com vetores parecidos.
        vetor = [0.0] * self.dimensao
        for palavra in re.findall(r"\w+", texto.lower()):
            if len(palavra) < 3:
                continue  # ignora "de", "o", "a"... que aparecem em todo texto
            # crc32 dá sempre o mesmo número para a mesma palavra
            # (o hash() do Python muda a cada execução).
            vetor[zlib.crc32(palavra.encode()) % self.dimensao] += 1.0
        return vetor

    def responder(self, prompt: str) -> str:
        # Sem LLM de verdade, devolvemos os próprios trechos que a busca encontrou.
        # Já dá para ver se a busca funcionou, sem gastar nada.
        trechos = prompt.split(MARCA_TRECHOS)[1].split(MARCA_PERGUNTA)[0].strip()
        return f"[modo fake] Trechos encontrados:\n{trechos}"

    def responder_stream(self, prompt: str) -> Iterator[str]:
        # Simula o LLM entregando palavra por palavra.
        # \S+\s* = "uma palavra + os espaços depois dela", para não perder espaços.
        yield from re.findall(r"\S+\s*", self.responder(prompt))


def montar_prompt(pergunta: str, trechos: list[Trecho]) -> str:
    """Junta instruções + trechos (com página) + pergunta num único texto para o LLM."""
    contexto = "\n\n".join(f"[Página {t.pagina}] {t.texto}" for t in trechos)
    return (
        "Você é um assistente que responde perguntas sobre um edital de licitação.\n"
        "Regras:\n"
        "- Responda APENAS com base nos trechos abaixo. Não use conhecimento externo.\n"
        f'- Se a resposta não estiver nos trechos, responda exatamente: "{NAO_ENCONTREI}".\n'
        "- Seja direto e cite a página de onde tirou a informação.\n\n"
        f"{MARCA_TRECHOS}\n{contexto}\n\n"
        f"{MARCA_PERGUNTA} {pergunta}"
    )


def criar_provedor() -> ProvedorIA:
    """Com chave no .env usa o Gemini; sem chave, entra no modo fake."""
    chave = os.getenv("GEMINI_API_KEY")
    return GeminiIA(chave) if chave else FakeIA()
