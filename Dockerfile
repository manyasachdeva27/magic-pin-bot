FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Single-worker: min=max=1 instance, CPU always allocated
ENV PORT=8080
ENV LLM_PROVIDER=none
ENV WORKERS=1

EXPOSE 8080

# Run with single worker — state is in-process, multi-worker would break state
CMD ["python", "-m", "uvicorn", "bot:app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "1", "--no-access-log"]
