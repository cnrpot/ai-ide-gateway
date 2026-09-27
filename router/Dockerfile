FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 复制成可导入的 `router` 包（build context = ./router）
COPY . /app/router/

EXPOSE 8080
CMD ["uvicorn", "router.app:app", "--host", "0.0.0.0", "--port", "8080"]
