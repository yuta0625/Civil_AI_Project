FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# ❌ これがあったら必ず削除
# ENTRYPOINT ["./entrypoint.sh"]
# CMD ["./entrypoint.sh"]

# 何も書かない（compose側で python を起動）
