FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 BELEGFLOW_SPEICHER=/srv/daten/belege
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
RUN useradd --system belegflow && mkdir -p daten/belege && chown -R belegflow daten
USER belegflow
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
