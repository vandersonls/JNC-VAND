FROM python:3.13-slim

# LibreOffice (só o componente Calc, mais leve que a suíte completa) para
# converter o molde de impressão da Lista por Desenho (Excel preenchido)
# em PDF idêntico - relatorios.py chama o binário `soffice`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-calc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120
