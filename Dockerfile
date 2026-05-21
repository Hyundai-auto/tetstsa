# Use a imagem oficial do Playwright
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

# Definir diretório de trabalho
WORKDIR /app

# Copiar arquivos de requisitos e instalar dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Garantir que o Chromium está instalado
RUN playwright install chromium

# Copiar o restante do código
COPY . .

# Expor a porta
EXPOSE 10000

# Comando para iniciar com Gunicorn e timeout estendido
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "120", "--workers", "1", "app:app"]
