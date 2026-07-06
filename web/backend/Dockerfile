# syntax=docker/dockerfile:1
# SuperPromt — веб-бэкенд (FastAPI-обёртка PSQ-конвейера).
# ВАЖНО: контекст сборки — КОРЕНЬ репозитория (бэкенду нужны пакет superprompt_cli и папка skills).
#   docker build -f web/backend/Dockerfile -t superpromt-web .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Слой зависимостей кэшируется отдельно от кода
COPY web/backend/requirements.txt ./web/backend/requirements.txt
RUN pip install --no-cache-dir -r web/backend/requirements.txt

# Код: ядро продукта (импортируется бэкендом), скиллы (читаются webskills) и веб-слой
COPY superprompt_cli/ ./superprompt_cli/
COPY skills/ ./skills/
COPY web/ ./web/

# Непривилегированный пользователь
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

# main.py сам добавляет корень репозитория в sys.path (через __file__),
# поэтому uvicorn запускается из каталога бэкенда.
WORKDIR /app/web/backend
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
