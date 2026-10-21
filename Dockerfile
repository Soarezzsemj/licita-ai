# Imagem "slim": Python 3.12 oficial, sem pacotes extras (imagem menor).
FROM python:3.12-slim

WORKDIR /code

# Copiamos o requirements.txt ANTES do código: o Docker guarda em cache a camada
# do pip install, e ela só é refeita quando as dependências mudam.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
# 0.0.0.0 = aceitar conexões de fora do container (o padrão 127.0.0.1 não aceitaria).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
