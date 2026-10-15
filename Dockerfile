# pandas、DuckDB 等套件在 Python 3.15 尚需從原始碼建置，因此只在建置階段安裝編譯工具。
FROM python:3.15-slim AS builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake ninja-build \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# W5 部署到 Render 時使用；W4 在 Codespaces 開發用不到
FROM python:3.15-slim

# 以非 root 使用者執行（uid 1000，沿用 HuggingFace 官方範例）
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/opt/venv/bin:/home/user/.local/bin:$PATH
WORKDIR $HOME/app

# 複製已建置的環境，正式映像不包含編譯工具
COPY --from=builder --chown=user /opt/venv /opt/venv

COPY --chown=user . .

# 使用 7860 埠：Render 的環境變數 PORT 要設成 7860
EXPOSE 7860
CMD ["solara", "run", "app.py", "--host=0.0.0.0", "--port=7860", "--production"]
