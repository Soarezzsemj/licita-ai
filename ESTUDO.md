# Guia de estudo: licita-ai

Material para entender o projeto a fundo e explicá-lo em entrevista.

---

## 1. Conceitos em linguagem simples

### Embedding
É um texto transformado numa **lista de números** (um vetor) que representa o seu **significado**.
Textos com sentidos parecidos viram vetores próximos, mesmo com palavras diferentes:
"prazo de entrega" fica perto de "em quanto tempo o produto chega".
No projeto, o Gemini gera vetores de 768 números. A `FakeIA` gera vetores de 256 números
contando palavras: ela só reconhece palavras **iguais**, não sinônimos.

### Similaridade de cosseno
É a forma de medir se dois vetores "apontam para o mesmo lado".
O resultado vai de -1 a 1, e quanto mais perto de 1, mais parecidos.
Ela mede a **direção** e ignora o **tamanho** do vetor. Por isso um trecho longo e uma
pergunta curta sobre o mesmo assunto continuam parecidos.
Fórmula: `cos = (A · B) / (|A| × |B|)`.
No projeto: `Distance.COSINE` em `app/conhecimento.py`.

### Chunking e sobreposição
**Chunking** é dividir o texto em trechos menores (aqui, cerca de 800 caracteres). Os motivos:
- a busca fica mais precisa, porque cada trecho fala de poucos assuntos;
- o prompt fica pequeno (mais barato e mais rápido).

**Sobreposição** (150 caracteres) é repetir o fim de um trecho no começo do próximo, para
que uma frase cortada no limite apareça inteira em pelo menos um deles.
Uma página de 1500 caracteres vira 3 trechos: 0–800, 650–1450 e 1300–1500.

### RAG (Retrieval-Augmented Generation)
É uma técnica para o LLM responder sobre documentos que ele nunca viu:
1. **Retrieval:** busca os trechos relevantes;
2. **Augmented:** coloca esses trechos no prompt;
3. **Generation:** o LLM gera a resposta usando esse contexto.

É o mesmo que fazer uma prova com consulta, onde o aluno só pode usar as páginas
que recebeu.

### Banco vetorial
É um banco de dados feito para guardar vetores e responder rápido à pergunta
"quais são os N vetores mais próximos deste?". Junto de cada vetor ele guarda um **payload**
(aqui, o texto e a página). Exemplos: Qdrant, Pinecone, pgvector.
No projeto o Qdrant roda em memória (`QdrantClient(":memory:")`): a API é a mesma de um
Qdrant de verdade, mas sem servidor separado.

### SSE (Server-Sent Events)
É um padrão HTTP em que o servidor mantém a resposta aberta e vai enviando eventos aos poucos.
Cada evento tem este formato:
```
event: texto
data: {"texto": "..."}
<linha em branco>
```
Ele vai só do servidor para o cliente, roda sobre HTTP comum e o navegador já tem suporte
nativo (`EventSource`). É ideal para mostrar a resposta do LLM enquanto ela é gerada,
como o ChatGPT faz.

### Classe abstrata
É uma classe que **não pode ser instanciada** e só define um **contrato**: "quem herdar de mim
precisa implementar estes métodos". Em Python: herdar de `ABC` e marcar os métodos com
`@abstractmethod`. É o equivalente a uma `interface` ou `abstract class` do C#.
No projeto, `ProvedorIA` exige `gerar_embedding`, `responder` e `responder_stream`.
A `GeminiIA` e a `FakeIA` cumprem esse contrato, e o resto do código não sabe qual das
duas está sendo usada.

### Injeção de dependência
Em vez de a rota **criar** o que precisa, ela **recebe** pronto de fora. No FastAPI:
`base: BaseDeConhecimento = Depends(obter_base)`.
A vantagem aparece nos testes: `app.dependency_overrides[obter_base] = ...` troca a base
real por uma com `FakeIA`, sem mudar nenhuma linha das rotas.
É a mesma ideia do `services.AddScoped<>()` do ASP.NET.

### Pydantic
É a biblioteca que valida dados usando as **anotações de tipo** do Python.
`pergunta: str = Field(min_length=5, max_length=500)` já garante tipo e tamanho.
Se a validação falhar, o FastAPI devolve **422** automaticamente, antes de a rota rodar.
Ele também converte a resposta em JSON e gera a documentação em `/docs`.

---

## 2. O caminho de uma pergunta pelos arquivos

Exemplo: `POST /perguntas/stream` com `{"pergunta": "Qual o prazo de entrega?"}`.

Antes disso o PDF já foi enviado: `enviar_documento` → `processar_pdf` (em `documentos.py`)
→ `base.indexar` (em `conhecimento.py`), que gera o embedding de cada trecho e o guarda no Qdrant.

1. **`app/main.py` → `perguntar_stream`:** o FastAPI recebe a requisição.
2. **`app/schemas.py` → `Pergunta`:** o Pydantic valida o JSON. Se a pergunta tiver menos de
   5 ou mais de 500 caracteres, a resposta é 422 e o processo para aqui.
3. **`app/main.py` → `obter_base`:** o `Depends` entrega a `BaseDeConhecimento`. Nos testes,
   é entregue a versão com `FakeIA`.
4. **`app/main.py` → `buscar_trechos`:** se ainda não houver edital, a resposta é **404**.
5. **`app/conhecimento.py` → `buscar`:** chama `ia.gerar_embedding(pergunta)`.
6. **`app/ia.py` → `GeminiIA.gerar_embedding`:** a pergunta vira um vetor de 768 números.
7. **`app/conhecimento.py` → `query_points`:** o Qdrant compara esse vetor com o de todos os
   trechos usando cosseno e devolve os 4 mais próximos. O texto e a página vêm do payload.
8. **`app/main.py` → `paginas_usadas`:** monta a lista das páginas desses 4 trechos,
   sem repetição e em ordem, por exemplo `[3, 7]`.
9. **`app/ia.py` → `montar_prompt`:** junta as regras, os trechos marcados com `[Página N]`
   e a pergunta num único texto.
10. **`app/main.py` → `gerar_eventos`:** chama `ia.responder_stream(prompt)`.
11. **`app/ia.py` → `GeminiIA.responder_stream`:** o Gemini gera a resposta e cada pedaço
    sai por um `yield`.
12. **`app/main.py` → `evento_sse`:** cada pedaço vira `event: texto`. No final vem
    `event: paginas`. O `StreamingResponse` envia cada evento assim que ele fica pronto.

No `POST /perguntas` sem streaming, o caminho é o mesmo até o passo 9. Depois a rota chama
`responder(prompt)` e devolve tudo de uma vez num `RespostaPergunta`.

---

## 3. Perguntas de entrevista (com respostas curtas)

**1. Por que não mandar o PDF inteiro para o LLM?**
Por quatro motivos: custo (paga-se por token), velocidade, limite de contexto (editais
podem ter centenas de páginas) e qualidade. Com muito texto irrelevante o modelo se perde
mais. Mandando só os 4 trechos relevantes, o prompt fica pequeno e focado.

**2. Como você evita que a IA invente coisas?**
Não dá para garantir 100%, mas reduzo o risco de três formas:
- o prompt manda responder **apenas** com os trechos e dá uma frase exata para quando não
  houver resposta ("Não encontrei essa informação no edital");
- a temperatura é baixa (0.1);
- a resposta mostra as **páginas** usadas, para o usuário conferir.

Em produção eu acrescentaria um limiar de similaridade mínima e avaliações automáticas.

**3. Por que ter um modo fake?**
Para que os testes rodem sem internet, sem chave, sem custo e com resultado sempre igual.
Também deixa qualquer pessoa rodar o projeto na hora. Como as duas IAs seguem o mesmo
contrato (`ProvedorIA`), o resto do código é exatamente o mesmo nos dois modos.

**4. Por que o Qdrant e não uma lista em memória?**
Com uma lista, eu teria que calcular o cosseno contra **todos** os vetores a cada pergunta,
o que é O(n) e não escala. O Qdrant usa índices (HNSW) para achar vizinhos próximos rápido,
guarda payload, permite filtros (por exemplo, por edital) e persiste os dados. Começar com
`:memory:` deixa trocar por um servidor real mudando só uma linha.

**5. Por que trechos de 800 caracteres com 150 de sobreposição?**
É um meio-termo. Trechos pequenos demais perdem contexto, e grandes demais misturam assuntos
e deixam a busca menos precisa. A sobreposição evita perder frases cortadas no limite.
Na prática, eu ajustaria esses números testando com perguntas reais e medindo se o trecho
certo aparece entre os 4 primeiros.

**6. Por que você não usou LangChain?**
Para entender e controlar cada passo do RAG. O fluxo tem poucas etapas e cabe em poucas
linhas. Sabendo fazer na mão, eu sei o que o framework faz por baixo e consigo depurar
quando algo dá errado.

**7. Para que serve a classe abstrata `ProvedorIA`?**
Ela desacopla o sistema do provedor. Trocar o Gemini por outro LLM é só criar uma nova
classe com os 3 métodos, sem mexer nas rotas nem na base. Isso é o princípio aberto/fechado
e a inversão de dependência do SOLID.

**8. Por que SSE e não WebSocket?**
A comunicação só vai do servidor para o cliente. SSE é HTTP comum, mais simples, passa por
proxies e o navegador já reconecta sozinho. WebSocket só valeria a pena se houvesse
conversa nos dois sentidos ao mesmo tempo.

**9. Como você trata um erro que acontece no meio do streaming?**
Depois do primeiro byte, o status 200 já foi enviado e não dá mais para mudar. Por isso:
- validações e o 404 acontecem **antes** de o streaming começar;
- uma falha durante a geração vira um evento `erro` dentro do próprio stream.

**10. Como você testou a API?**
Com 8 testes no pytest usando o `TestClient` do FastAPI. Um *fixture* troca a dependência
`obter_base` por uma base nova com `FakeIA` em cada teste, então os testes ficam isolados
uns dos outros e rodam offline. O PDF é gerado dentro do teste com `fpdf2`, e os testes
cobrem os status 201, 400, 404 e 422, o chunking e o formato do SSE.

**11. O que acontece se dois usuários enviarem editais ao mesmo tempo?**
Hoje a base é global e um upload substitui o outro. Essa limitação é consciente, para manter
o projeto simples. A solução seria ter autenticação (JWT), um id de documento no payload do
Qdrant e um filtro por usuário ou documento na busca.

**12. Como você levaria isso para produção?**
- Qdrant como serviço próprio (Docker Compose), para os dados persistirem;
- PostgreSQL para o histórico;
- Redis para cache e *rate limiting*;
- JWT para autenticação;
- embeddings em lote e processamento do upload em segundo plano, para PDFs grandes;
- logs e métricas, por exemplo de latência e de quantas vezes a resposta foi "não encontrei".

---

## 4. Resumo de 1 minuto (para falar em voz alta)

> "O licita-ai é uma API em Python com FastAPI que responde perguntas sobre editais de
> licitação. Eu implementei RAG do zero, sem LangChain, para entender cada etapa.
>
> Quando o usuário envia o PDF, eu extraio o texto página por página e divido em trechos
> de 800 caracteres com 150 de sobreposição, para não cortar informação no meio. Cada trecho
> vira um embedding pelo Gemini e vai para o Qdrant junto com o número da página.
>
> Na pergunta, eu gero o embedding dela, busco os 4 trechos mais parecidos por similaridade
> de cosseno e monto um prompt mandando o LLM responder só com aqueles trechos, ou dizer que
> não encontrou. A resposta volta em streaming por Server-Sent Events, e no final mando as
> páginas usadas, para o usuário conferir a fonte.
>
> No design, usei uma classe abstrata para o provedor de IA, com duas implementações: o
> Gemini e uma versão fake. Com a injeção de dependência do FastAPI, os testes usam a versão
> fake e rodam sem internet. O projeto tem testes com pytest, validação com Pydantic e
> Dockerfile.
>
> Com mais tempo, eu colocaria Qdrant como serviço com Docker Compose, PostgreSQL para o
> histórico, autenticação JWT e Redis para cache."
