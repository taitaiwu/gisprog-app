# W5 部署到 Render 時使用；W4 在 Codespaces 開發用不到
# 用 3.12：requirements.txt 的套件都有現成 wheel（3.15 的 duckdb 1.5.6 沒有，要從原始碼編譯，Render 會建置失敗）
FROM python:3.12-slim

# 以非 root 使用者執行（uid 1000，沿用 HuggingFace 官方範例）
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .

# 使用 7860 埠：Render 的環境變數 PORT 要設成 7860
EXPOSE 7860
CMD ["solara", "run", "app.py", "--host=0.0.0.0", "--port=7860", "--production"]
