"""Leitura do PDF e divisão do texto em trechos (chunking)."""

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

# ~800 caracteres cabem bem num prompt e ainda carregam contexto suficiente.
TAMANHO_TRECHO = 800
# A sobreposição evita que uma frase importante seja cortada ao meio
# e fique "perdida" entre dois trechos.
SOBREPOSICAO = 150


@dataclass
class Trecho:
    """Um pedaço de texto e a página de onde ele veio (para citar a fonte)."""

    texto: str
    pagina: int


def extrair_paginas(conteudo: bytes) -> list[str]:
    """Devolve o texto de cada página, na ordem. Página sem texto vira ""."""
    leitor = PdfReader(BytesIO(conteudo))  # BytesIO: trata os bytes como um arquivo
    return [pagina.extract_text() or "" for pagina in leitor.pages]


def dividir_em_trechos(texto: str, pagina: int) -> list[Trecho]:
    """Corta o texto em janelas de TAMANHO_TRECHO que andam de (TAMANHO - SOBREPOSICAO)."""
    texto = " ".join(texto.split())  # junta quebras de linha e espaços repetidos
    passo = TAMANHO_TRECHO - SOBREPOSICAO
    trechos: list[Trecho] = []
    for inicio in range(0, len(texto), passo):
        pedaco = texto[inicio : inicio + TAMANHO_TRECHO].strip()
        trechos.append(Trecho(pedaco, pagina))
        if inicio + TAMANHO_TRECHO >= len(texto):
            break  # este trecho já chegou ao fim do texto
    return trechos


def processar_pdf(conteudo: bytes) -> list[Trecho]:
    """PDF -> lista de trechos. Dividimos página por página para saber a página exata."""
    trechos: list[Trecho] = []
    for numero, texto in enumerate(extrair_paginas(conteudo), start=1):
        trechos.extend(dividir_em_trechos(texto, numero))
    return trechos
