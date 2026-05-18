FROM python:3.11-slim

WORKDIR /app

COPY requirements_cloud.txt .
RUN pip install --no-cache-dir -r requirements_cloud.txt
RUN pip install --no-cache-dir torch==2.3.0 --index-url https://download.pytorch.org/whl/cpu

COPY . .

# Cloud Run は PORT 環境変数でポートを指定する
CMD ["sh", "-c", "python -m uvicorn api.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
