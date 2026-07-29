FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY fixtures ./fixtures

# Sicherheit: als unprivilegierter Nutzer laufen, nicht als root
RUN useradd --create-home --uid 10001 botuser \
    && mkdir -p /app/data \
    && chown -R botuser:botuser /app
USER botuser

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
