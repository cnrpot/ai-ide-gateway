# QoderGateway (bzym2/QoderGateway) — 上游无 Dockerfile，这里补一个。
# 坑：pyproject.toml 把 pypiwin32/drissionpage 列成无平台标记的强依赖，
#     Linux 上直接 `pip install .` 会失败 -> 只手装核心运行依赖 + `--no-deps` 装包体。
#     registrar 的 win32/drissionpage 都是函数内惰性 import，不装也能正常启动
#     （只是不启用注册机；本聚合网关用不到它）。
# build context = 仓库根目录（才能 COPY providers/qoder）。

# ---- stage 1: 构建前端（vite），产物写入上游配置的 static 目录 ----
FROM node:20-slim AS frontend
WORKDIR /src
COPY providers/qoder/ /src/
WORKDIR /src/frontend
RUN npm ci && npm run build && rm -rf node_modules

# ---- stage 2: python 运行时 ----
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    QODER_HOST=0.0.0.0 QODER_PORT=5050 HOME=/data \
    PYTHONPATH=/app/src

RUN pip install --no-cache-dir \
      "cryptography>=43.0.0" "fastapi>=0.115.0" "httpx>=0.27.0" "uvicorn[standard]>=0.30.6"

# 带 static 产物的完整源码树（stage1 已删 node_modules）
COPY --from=frontend /src /app
COPY docker/qoder-entrypoint.py /usr/local/bin/qoder-entrypoint.py
RUN pip install --no-cache-dir --no-deps . && mkdir -p /data/.qoder

VOLUME ["/data/.qoder"]
EXPOSE 5050
CMD ["python3", "/usr/local/bin/qoder-entrypoint.py"]
