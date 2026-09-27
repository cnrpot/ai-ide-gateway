# codebuddy2api (ShouZhuo0413/codebuddy2api) 的 admin 控制台后端。
# 上游 deploy/admin/Dockerfile 依赖预构建基础镜像（ARG BASE_IMAGE），有构建顺序依赖；
# 这里自写一个独立镜像绕开那层间接。
# admin.server 的 __main__ 固定 uvicorn.run(host="0.0.0.0", port=8787)，
# 因此 router 可用 http://codebuddy:8787 直连。
# build context = 仓库根目录（才能 COPY providers/codebuddy）。
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    CODEBUDDY_AUTH_DIR=/data/auth MANAGEMENT_DATA_DIR=/data/management \
    TZ=Asia/Shanghai

# 上游仅 3 个依赖，显式安装（不依赖根 requirements.txt 是否存在）
RUN pip install --no-cache-dir "fastapi>=0.115.0" "uvicorn[standard]>=0.30.0" "httpx>=0.27.0"

COPY providers/codebuddy/core /app/core
COPY providers/codebuddy/admin /app/admin
RUN mkdir -p /data/auth /data/management

VOLUME ["/data/auth", "/data/management"]
EXPOSE 8787
CMD ["python3", "-m", "admin.server"]
