FROM python:3.11-slim

WORKDIR /app

ENV TZ=Asia/Ho_Chi_Minh

# Cài đặt thư viện hệ thống cơ bản và dữ liệu múi giờ
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

