# licita-ai

Assistente que responde perguntas sobre **editais de licitação em PDF**, usando RAG
(*Retrieval-Augmented Generation*) feito "na mão", sem LangChain.

Você envia o edital, pergunta "Qual o prazo de entrega?" e recebe a resposta, gerada
**somente** a partir do texto do edital, junto com as páginas usadas como fonte.

**Stack:** Python 3.12 · FastAPI · Pydantic · pypdf · Qdrant (em memória) · Google Gemini · pytest · Docker

## Como funciona

```
 INDEXAÇÃO (POST /documentos)
 ┌─────┐   pypdf    ┌──────────┐  chunking   ┌──────────────┐  embedding  ┌────────────┐
 │ PDF │ ─────────▶ │ texto de │ ──────────▶ │ trechos de   │ ──────────▶ │   Qdrant   │
 └─────┘            │ cada pág.│ 800 chars,  │ ~800 chars   │  (vetores)  │ vetor +    │
                    └──────────┘ 150 sobrep. └──────────────┘             │ texto+pág. │
                                                                          └─────┬──────┘
 PERGUNTA (POST /perguntas ou /perguntas/stream)                                │
 ┌──────────┐ embedding ┌───────────┐  busca por cosseno  ┌────────────────┐     │
 │ pergunta │ ────────▶ │  vetor da │ ──────────────────▶ │ 4 trechos mais │ ◀───┘
 └──────────┘           │  pergunta │                     │   parecidos    │
                        └───────────┘                     └───────┬────────┘
                                                                  ▼
 ┌───────────────────────┐   streaming (SSE)   ┌─────┐   ┌──────────────────────────┐
 │ resposta em pedaços + │ ◀────────────────── │ LLM │ ◀ │ prompt = regras +        │
 │ páginas no fim        │                     └─────┘   │ trechos + pergunta       │
 └───────────────────────┘                               └──────────────────────────┘
```

## Estrutura

| Arquivo | Responsabilidade |
|---|---|
| `app/main.py` | Rotas da API, validações HTTP e injeção de dependência |
| `app/documentos.py` | Extrai o texto do PDF e divide em trechos (chunking) |
| `app/ia.py` | `ProvedorIA` (abstrata), `GeminiIA`, `FakeIA` e montagem do prompt |
| `app/conhecimento.py` | `BaseDeConhecimento`: guarda e busca trechos no Qdrant |
| `app/schemas.py` | Modelos Pydantic de entrada e saída |
| `tests/test_api.py` | 8 testes com pytest usando a `FakeIA` |

## Como rodar

### Localmente

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   |   Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abra http://localhost:8000/docs para testar pela documentação interativa (Swagger).

- **Sem chave (modo fake):** é só rodar. Os embeddings são feitos a partir das palavras
  e o "LLM" devolve os trechos encontrados. Não precisa de internet.
- **Com chave (Gemini):** copie `.env.example` para `.env` e preencha `GEMINI_API_KEY`
  (gere em https://aistudio.google.com/apikey). Reinicie a API.

### Com Docker

```bash
docker build -t licita-ai .
docker run -p 8000:8000 licita-ai                  # modo fake
docker run -p 8000:8000 --env-file .env licita-ai  # com Gemini
```

### Testes

```bash
pytest
```

Os testes trocam a base por uma com `FakeIA` (via `app.dependency_overrides`),
então rodam sem chave e sem internet.

## Exemplos com curl

```bash
# Saúde da API
curl localhost:8000/health

# Enviar um edital  ->  201 {"arquivo": "edital.pdf", "trechos": 42}
curl -F "arquivo=@edital.pdf" localhost:8000/documentos

# Perguntar  ->  {"resposta": "...", "paginas": [3, 7]}
curl -X POST localhost:8000/perguntas \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Qual o prazo de entrega?"}'

# Perguntar com streaming (-N mostra os eventos conforme chegam)
curl -N -X POST localhost:8000/perguntas/stream \
  -H "Content-Type: application/json" \
  -d '{"pergunta": "Qual o prazo de entrega?"}'
```

Saída do streaming:

```
event: texto
data: {"texto": "O prazo de entrega é de "}

event: texto
data: {"texto": "30 dias corridos (página 3)."}

event: paginas
data: {"paginas": [3, 7]}
```

> No PowerShell, use `curl.exe` e passe o JSON por arquivo (`-d "@pergunta.json"`),
> porque o PowerShell altera as aspas da string. Ou rode os comandos no Git Bash.

### Códigos de resposta

| Situação | Status |
|---|---|
| Upload de PDF válido | 201 |
| Arquivo que não é PDF, PDF corrompido ou sem texto | 400 |
| Pergunta antes de enviar um edital | 404 |
| Pergunta com menos de 5 ou mais de 500 caracteres | 422 |

## Decisões de projeto

- **Chunking por página:** cada trecho pertence a uma única página, então a fonte citada é exata.
  O custo é que uma frase que atravessa a virada de página fica cortada.
- **Um edital por vez:** um novo upload substitui o anterior. É mais simples, e a pergunta
  é sempre sobre "o edital".
- **Busca antes do streaming:** o erro 404 só pode ser enviado antes do primeiro byte do stream.
  Uma falha no meio do caminho vira um evento `erro`.
- **Temperatura 0.1** e instruções rígidas no prompt para reduzir respostas inventadas.

## O que eu melhoraria com mais tempo

- **Docker Compose com Qdrant real:** os dados sobreviveriam a reinícios e o Qdrant poderia
  escalar separadamente da API. Bastaria trocar `QdrantClient(":memory:")` por
  `QdrantClient(url="http://qdrant:6333")`.
- **PostgreSQL** para guardar o histórico de perguntas e respostas e os metadados dos editais.
- **Autenticação JWT**, para cada usuário ter os próprios editais (hoje a base é global).
- **Redis** como cache de respostas para perguntas repetidas e para *rate limiting*.
- **Vários editais ao mesmo tempo**, filtrando a busca pelo id do documento no *payload* do Qdrant.
- **Embeddings em lote** (uma chamada para vários trechos) para indexar PDFs grandes mais rápido.
- **OCR** para PDFs escaneados, que hoje são recusados por não terem texto.
- Devolver `paginas: []` quando o LLM responder "Não encontrei essa informação no edital".
- Separar as dependências de teste (`pytest`, `fpdf2`) num `requirements-dev.txt`.
