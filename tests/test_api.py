"""Testes da API usando a FakeIA: rodam sem chave e sem internet."""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from app.conhecimento import BaseDeConhecimento
from app.documentos import dividir_em_trechos
from app.ia import FakeIA
from app.main import app, obter_base

PAGINAS_DO_EDITAL = [
    "Objeto: aquisição de computadores para as escolas municipais.",
    "O prazo de entrega dos equipamentos é de 30 dias corridos após a assinatura.",
    "A garantia mínima exigida é de 12 meses contra defeitos de fabricação.",
]


def criar_pdf(paginas: list[str]) -> bytes:
    """Gera um PDF em memória, com um texto por página."""
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for texto in paginas:
        pdf.add_page()
        pdf.multi_cell(0, 10, texto)
    return bytes(pdf.output())


@pytest.fixture
def cliente() -> Iterator[TestClient]:
    """Cada teste ganha uma base nova com FakeIA (injeção de dependência)."""
    base_de_teste = BaseDeConhecimento(FakeIA())
    app.dependency_overrides[obter_base] = lambda: base_de_teste
    yield TestClient(app)
    app.dependency_overrides.clear()  # não deixa a troca "vazar" para outros testes


def enviar_edital(cliente: TestClient) -> dict:
    arquivo = ("edital.pdf", criar_pdf(PAGINAS_DO_EDITAL), "application/pdf")
    resposta = cliente.post("/documentos", files={"arquivo": arquivo})
    assert resposta.status_code == 201
    return resposta.json()


def test_health(cliente: TestClient) -> None:
    resposta = cliente.get("/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_pagina_inicial_e_html(cliente: TestClient) -> None:
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")


def test_chunking_com_sobreposicao() -> None:
    # 1500 caracteres -> trechos começando em 0, 650 e 1300
    texto = "".join(str(i % 10) for i in range(1500))
    trechos = dividir_em_trechos(texto, pagina=1)
    assert [len(t.texto) for t in trechos] == [800, 800, 200]
    assert trechos[0].texto[-150:] == trechos[1].texto[:150]  # a sobreposição


def test_upload_de_pdf_indexa_trechos(cliente: TestClient) -> None:
    dados = enviar_edital(cliente)
    assert dados == {"arquivo": "edital.pdf", "trechos": 3}  # 1 trecho por página


def test_upload_de_arquivo_que_nao_e_pdf_retorna_400(cliente: TestClient) -> None:
    arquivo = ("edital.txt", b"isso nao e um pdf", "text/plain")
    resposta = cliente.post("/documentos", files={"arquivo": arquivo})
    assert resposta.status_code == 400


def test_pergunta_antes_do_upload_retorna_404(cliente: TestClient) -> None:
    resposta = cliente.post("/perguntas", json={"pergunta": "Qual o prazo de entrega?"})
    assert resposta.status_code == 404


def test_pergunta_fora_do_tamanho_retorna_422(cliente: TestClient) -> None:
    assert cliente.post("/perguntas", json={"pergunta": "oi"}).status_code == 422
    assert cliente.post("/perguntas", json={"pergunta": "a" * 501}).status_code == 422


def test_pergunta_responde_com_trecho_certo_e_paginas(cliente: TestClient) -> None:
    enviar_edital(cliente)
    resposta = cliente.post("/perguntas", json={"pergunta": "Qual o prazo de entrega?"})
    dados = resposta.json()
    assert resposta.status_code == 200
    # A FakeIA devolve os trechos em ordem de similaridade: o 1º deve ser o do prazo.
    assert dados["resposta"].splitlines()[1].startswith("[Página 2] O prazo de entrega")
    assert 2 in dados["paginas"]


def test_stream_envia_pedacos_e_termina_com_paginas(cliente: TestClient) -> None:
    enviar_edital(cliente)
    resposta = cliente.post("/perguntas/stream", json={"pergunta": "Qual a garantia?"})
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/event-stream")

    eventos = resposta.text.strip().split("\n\n")  # linha em branco separa eventos
    assert eventos[0].startswith("event: texto")
    ultimo_nome, ultimo_dado = eventos[-1].split("\n")
    assert ultimo_nome == "event: paginas"
    assert 3 in json.loads(ultimo_dado.removeprefix("data: "))["paginas"]
