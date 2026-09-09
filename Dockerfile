FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgobject-2.0-0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-gobject0 \
    libopenjp2-7 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* /app/
RUN uv sync --frozen

COPY . /app

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]

