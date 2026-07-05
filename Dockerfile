FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py .
COPY config.yaml .
COPY src/ src/
COPY static/ static/

# 环境变量
ENV PORT=8000

EXPOSE 8000

CMD ["python", "app.py"]
