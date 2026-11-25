FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libegl1 libgles2 libgomp1 \
    && (apt-get install -y --no-install-recommends libglib2.0-0t64 \
        || apt-get install -y --no-install-recommends libglib2.0-0) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0 torchvision

COPY requirements.txt .
RUN pip install -r requirements.txt lap

COPY . .

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]