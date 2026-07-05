"""
低空经济气象任务助手 - 线上部署版本
FastAPI 同时托管 API 和前端静态文件
"""
import sys
import os
import yaml
import logging
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional, List

# 路径设置
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from src.weather_api import OpenMeteoClient
from src.task_analyzer import DroneTaskAnalyzer

# 日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# 配置
config_path = BASE_DIR / "config.yaml"
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 全局实例（模块级初始化，兼容无 lifespan 场景）
api_config = config.get('weather_api', {}).get('open_meteo', {})
weather_client = OpenMeteoClient(
    base_url=api_config.get('base_url', 'https://api.open-meteo.com/v1'),
    geocoding_url=api_config.get('geocoding_url', 'https://geocoding-api.open-meteo.com/v1')
)
task_analyzer = DroneTaskAnalyzer(str(config_path))
logger.info("服务组件初始化完成")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("服务已启动")
    yield
    await weather_client.close()
    logger.info("服务已关闭")


app = FastAPI(
    title="低空经济气象任务助手",
    description="基于真实气象数据的无人机飞行窗口评估系统",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === 请求模型 ===
class AssessmentRequest(BaseModel):
    query: str
    drone_type: str = "consumer"

class GeocodeRequest(BaseModel):
    location: str

class ForecastRequest(BaseModel):
    latitude: float
    longitude: float
    hours: int = 72


# === API端点 ===

@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.post("/api/assess")
async def assess_flight_task(request: AssessmentRequest):
    try:
        logger.info(f"评估请求: {request.query}")
        parsed = task_analyzer.parse_user_request(request.query)
        location = parsed.get("location", "")
        
        if not location:
            raise HTTPException(status_code=400, detail="无法识别地点，请明确城市名称，如：深圳、北京、上海")
        
        forecast_data = await weather_client.get_forecast_by_location(location, hours=72)
        result = task_analyzer.generate_full_assessment(
            request.query, forecast_data["forecasts"], forecast_data["location"]
        )
        response = task_analyzer.result_to_dict(result)
        logger.info(f"评估完成: {result.location}, 风险={result.overall_risk.value}")
        return {"success": True, "data": response}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"评估失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"评估失败: {str(e)}")


@app.post("/api/geocode")
async def geocode_location(request: GeocodeRequest):
    try:
        result = await weather_client.geocode(request.location)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到地点: {request.location}")
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/forecast")
async def get_forecast(request: ForecastRequest):
    try:
        forecasts = await weather_client.get_hourly_forecast(
            request.latitude, request.longitude, request.hours
        )
        return {"success": True, "data": [f.to_dict() for f in forecasts]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rules")
async def get_flight_rules():
    return {"success": True, "data": config.get("flight_rules", {})}


@app.get("/api/cities")
async def get_popular_cities():
    cities = [
        {"name": "深圳", "lat": 22.5431, "lon": 114.0579},
        {"name": "广州", "lat": 23.1291, "lon": 113.2644},
        {"name": "北京", "lat": 39.9042, "lon": 116.4074},
        {"name": "上海", "lat": 31.2304, "lon": 121.4737},
        {"name": "杭州", "lat": 30.2741, "lon": 120.1551},
        {"name": "成都", "lat": 30.5728, "lon": 104.0668},
        {"name": "武汉", "lat": 30.5928, "lon": 114.3055},
        {"name": "南京", "lat": 32.0603, "lon": 118.7969},
        {"name": "重庆", "lat": 29.4316, "lon": 106.9123},
        {"name": "西安", "lat": 34.3416, "lon": 108.9398},
        {"name": "长沙", "lat": 28.2282, "lon": 112.9388},
        {"name": "青岛", "lat": 36.0671, "lon": 120.3826},
    ]
    return {"success": True, "data": cities}


# === 前端静态文件 ===
STATIC_DIR = BASE_DIR / "static"

@app.get("/")
async def serve_index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html")
    return HTMLResponse("<h1>低空经济气象任务助手</h1><p>前端文件未找到</p>")


# === 启动 ===
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
    )
