# Путь: services/core/Dockerfile
FROM ghcr.io/astral-sh/uv:0.9 AS uv_bin

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=uv_bin /uv /uvx /bin/

# Копируем файл конфигурации зависимостей (относительно корня репозитория)
COPY services/core/pyproject.toml ./

# Устанавливаем зависимости в виртуальное окружение
RUN uv venv .venv && \
    uv pip install --no-cache -r pyproject.toml

# Копируем исходный код бэкенда
COPY services/core/core ./core

EXPOSE 8000

CMD ["uvicorn", "core.api:app", "--host", "0.0.0.0", "--port", "8000"]
