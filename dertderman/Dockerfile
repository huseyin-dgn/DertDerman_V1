FROM python:3.10.21-slim-bookworm@sha256:68d914ec641a0b69267ce65184d000a2bc3a9ee2590ab702b82250ab2385735a

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update     && apt-get upgrade -y     && rm -rf /var/lib/apt/lists/*

RUN groupadd --system dertderman \
    && useradd \
        --system \
        --gid dertderman \
        --create-home \
        dertderman

COPY requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade \
        pip \
        setuptools==78.1.1 \
        wheel==0.46.2 \
    && python -m pip install \
        -r /app/requirements.txt

COPY . /app

RUN mkdir -p \
        /var/lib/dertderman/static \
        /var/lib/dertderman/media \
    && chown -R \
        dertderman:dertderman \
        /app \
        /var/lib/dertderman

USER dertderman

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind=0.0.0.0:8000", "--workers=2", "--threads=2", "--timeout=60", "--error-logfile=-"]
