FROM python:3.10.18-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system dertderman \
    && useradd \
        --system \
        --gid dertderman \
        --create-home \
        dertderman

COPY requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip \
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
