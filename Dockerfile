FROM python:3.12-slim

# 不寫 .pyc — 搭配 compose 的 read_only
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app/ ./app/
COPY web/ ./web/
COPY prompts/ ./prompts/

EXPOSE 8091
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091"]
