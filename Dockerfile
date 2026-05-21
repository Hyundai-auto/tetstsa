# Use a imagem oficial do Playwright que já vem com tudo configurado
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
EXPOSE 5000

# Comando para iniciar a aplicação
CMD ["python", "app.py"]
