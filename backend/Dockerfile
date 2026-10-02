FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 codeblog \
    && useradd --uid 10001 --gid codeblog --no-create-home codeblog \
    && mkdir -p /data /app/backend/uploads \
    && chown -R codeblog:codeblog /data /app/backend
COPY --chown=codeblog:codeblog . .
USER codeblog
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
