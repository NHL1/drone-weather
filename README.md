# 低空经济气象任务助手 - 线上部署指南

## 项目结构

```
deploy/
├── app.py              # FastAPI 主应用（API + 静态文件托管）
├── config.yaml         # 飞行规则配置
├── requirements.txt    # Python 依赖
├── Dockerfile          # Docker 部署
├── Procfile            # Railway/Heroku 部署
├── src/
│   ├── weather_api.py  # Open-Meteo 气象 API
│   └── task_analyzer.py # 任务分析引擎
└── static/
    └── index.html      # 前端页面（CDN版，无需构建）
```

---

## 方式一：Railway（推荐，最简单）

1. 访问 https://railway.app 注册/登录
2. 点击 **New Project** → **Deploy from GitHub repo**
3. 上传整个 `deploy/` 目录到你的 GitHub 仓库
4. Railway 自动检测 Dockerfile 并构建
5. 部署完成后，在 **Settings → Networking** 中获取公网域名

> 免费额度：$5/月（约可运行 500 小时），足够个人使用

---

## 方式二：Render

1. 访问 https://render.com 注册/登录
2. 点击 **New** → **Web Service**
3. 连接你的 GitHub 仓库（deploy 目录）
4. 配置：
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
   - **Environment**: `PORT=8000`
5. 点击 **Create Web Service**

> 免费套餐可用，首次启动较慢（冷启动约30秒）

---

## 方式三：Docker 本地/服务器部署

```bash
# 构建镜像
cd deploy/
docker build -t drone-weather .

# 运行
docker run -d -p 8000:8000 --name drone-weather drone-weather
```

访问 http://localhost:8000

---

## 方式四：VPS 直接部署

```bash
# 安装依赖
pip install -r requirements.txt

# 启动
python app.py
```

配合 Nginx 反向代理即可对外提供服务。

---

## API 文档

部署后可访问：
- **首页**: `https://你的域名/`
- **API文档**: `https://你的域名/docs`（Swagger UI）
- **健康检查**: `GET /api/health`
- **飞行评估**: `POST /api/assess`
  ```json
  {"query": "明天下午2-5点北京国贸能飞航拍吗", "drone_type": "consumer"}
  ```

## 数据源

- 气象数据：[Open-Meteo](https://open-meteo.com)（免费、无需API Key）
- 覆盖范围：全球
- 更新频率：逐小时
- 预报时长：最长7天
