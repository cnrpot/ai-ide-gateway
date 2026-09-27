FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# build context = ./checkin -> 复制成可导入的 `checkin` 包
COPY . /app/checkin/

CMD ["python", "-m", "checkin.scheduler"]
