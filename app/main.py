"""Ponto de entrada da API: define as rotas e liga as peças."""

import json
from collections.abc import Iterator

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pypdf.errors import PdfReadError

from app.conhecimento import BaseDeConhecimento
from app.documentos import Trecho, processar_pdf
from app.ia import ProvedorIA, criar_provedor, montar_prompt
from app.schemas import Pergunta, RespostaPergunta, RespostaUpload

load_dotenv()  # lê o .env e coloca GEMINI_API_KEY nas variáveis de ambiente

app = FastAPI(title="licita-ai")

# Uma única base para a API toda: como o Qdrant está em memória,
# o PDF enviado num request precisa estar lá no request da pergunta.
base = BaseDeConhecimento(criar_provedor())


def obter_base() -> BaseDeConhecimento:
    """Dependência injetada nas rotas. Nos testes ela é trocada por uma base com FakeIA."""
    return base


@app.get("/health")
def health() -> dict[str, str]:
    """Rota simples para saber se a API está no ar (útil para Docker e monitoramento)."""
    return {"status": "ok"}


@app.post("/documentos", status_code=201, response_model=RespostaUpload)
def enviar_documento(
    arquivo: UploadFile = File(...),
    base: BaseDeConhecimento = Depends(obter_base),
) -> RespostaUpload:
    conteudo = arquivo.file.read()
    nome = arquivo.filename or ""
    # Checamos a extensão E a "assinatura" do arquivo: todo PDF começa com %PDF.
    # Só a extensão não basta, pois qualquer arquivo pode ser renomeado.
    if not nome.lower().endswith(".pdf") or not conteudo.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF.")
    try:
        trechos = processar_pdf(conteudo)
    except PdfReadError:
        raise HTTPException(status_code=400, detail="O PDF está corrompido.")
    if not trechos:
        # Acontece com PDFs escaneados (só imagem): não há texto para extrair.
        raise HTTPException(status_code=400, detail="Não encontrei texto no PDF.")
    return RespostaUpload(arquivo=nome, trechos=base.indexar(trechos))


def buscar_trechos(base: BaseDeConhecimento, pergunta: str) -> list[Trecho]:
    """Passo de "retrieval" do RAG, compartilhado pelas rotas normal e de streaming."""
    if not base.tem_documento():
        raise HTTPException(status_code=404, detail="Envie um edital antes de perguntar.")
    return base.buscar(pergunta, limite=4)


def paginas_usadas(trechos: list[Trecho]) -> list[int]:
    """Páginas sem repetição e em ordem, ex.: [3, 7]."""
    return sorted({t.pagina for t in trechos})


@app.post("/perguntas", response_model=RespostaPergunta)
def perguntar(
    dados: Pergunta, base: BaseDeConhecimento = Depends(obter_base)
) -> RespostaPergunta:
    trechos = buscar_trechos(base, dados.pergunta)          # 1. busca (Retrieval)
    prompt = montar_prompt(dados.pergunta, trechos)          # 2. prompt (Augmented)
    resposta = base.ia.responder(prompt)                     # 3. LLM (Generation)
    return RespostaPergunta(resposta=resposta, paginas=paginas_usadas(trechos))


def evento_sse(nome: str, dados: dict) -> str:
    """Formata um evento SSE: linha "event:", linha "data:" e uma linha em branco no fim.

    Usamos JSON no "data" porque o texto do LLM pode ter quebras de linha,
    e uma quebra de linha crua seria lida como fim de campo pelo SSE.
    """
    return f"event: {nome}\ndata: {json.dumps(dados, ensure_ascii=False)}\n\n"


def gerar_eventos(ia: ProvedorIA, prompt: str, paginas: list[int]) -> Iterator[str]:
    try:
        for pedaco in ia.responder_stream(prompt):
            yield evento_sse("texto", {"texto": pedaco})
        yield evento_sse("paginas", {"paginas": paginas})  # último evento: as fontes
    except Exception:
        # O status 200 já foi enviado quando o streaming começou;
        # a única forma de avisar uma falha no meio do caminho é mandar um evento.
        yield evento_sse("erro", {"detalhe": "Falha ao gerar a resposta."})


@app.post("/perguntas/stream")
def perguntar_stream(
    dados: Pergunta, base: BaseDeConhecimento = Depends(obter_base)
) -> StreamingResponse:
    # A busca roda ANTES de começar o streaming: assim o 404 ainda pode ser devolvido.
    trechos = buscar_trechos(base, dados.pergunta)
    prompt = montar_prompt(dados.pergunta, trechos)
    eventos = gerar_eventos(base.ia, prompt, paginas_usadas(trechos))
    return StreamingResponse(eventos, media_type="text/event-stream")
