"""
Open-Meteo 气象API接入模块
免费、无需API Key、全球覆盖
文档：https://open-meteo.com/en/docs
"""
import httpx
from typing import Optional, List, Dict
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class HourlyWeatherData:
    """逐小时气象数据"""
    time: str                          # ISO格式时间
    temperature_2m: float              # 2m温度（℃）
    relative_humidity_2m: int          # 2m相对湿度（%）
    wind_speed_10m: float              # 10m风速（km/h）
    wind_gusts_10m: Optional[float]    # 10m阵风（km/h）
    wind_direction_10m: int            # 10m风向（度）
    visibility: Optional[float]        # 能见度（m）
    precipitation: float               # 降水量（mm）
    rain: float                        # 降雨量（mm）
    snowfall: float                    # 降雪量（cm）
    weather_code: int                  # WMO天气代码
    cloud_cover: int                   # 云量（%）
    cloud_ceiling: Optional[float]     # 云底高度（m）
    
    # 派生属性
    @property
    def wind_speed_ms(self) -> float:
        """风速转换为m/s"""
        return self.wind_speed_10m / 3.6
    
    @property
    def wind_gust_ms(self) -> Optional[float]:
        """阵风转换为m/s"""
        if self.wind_gusts_10m is not None:
            return self.wind_gusts_10m / 3.6
        return None
    
    @property
    def visibility_km(self) -> float:
        """能见度转换为km"""
        if self.visibility is not None:
            return self.visibility / 1000.0
        return 10.0  # 默认10km
    
    @property
    def datetime_obj(self) -> datetime:
        """解析时间"""
        # Open-Meteo返回格式: 2024-01-15T08:00
        return datetime.fromisoformat(self.time)
    
    @property
    def weather_text(self) -> str:
        """WMO天气代码转换为中文描述"""
        wmo_codes = {
            0: "晴",
            1: "大部晴朗", 2: "多云", 3: "阴",
            45: "雾", 48: "雾凇",
            51: "轻微毛毛雨", 53: "中等毛毛雨", 55: "浓密毛毛雨",
            56: "冻毛毛雨", 57: "浓密冻毛毛雨",
            61: "小雨", 63: "中雨", 65: "大雨",
            66: "冻雨", 67: "大冻雨",
            71: "小雪", 73: "中雪", 75: "大雪",
            77: "雪粒",
            80: "小阵雨", 81: "中阵雨", 82: "大阵雨",
            85: "小阵雪", 86: "大阵雪",
            95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹"
        }
        return wmo_codes.get(self.weather_code, f"未知({self.weather_code})")
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "time": self.time,
            "temperature": self.temperature_2m,
            "humidity": self.relative_humidity_2m,
            "wind_speed": round(self.wind_speed_ms, 1),
            "wind_gust": round(self.wind_gust_ms, 1) if self.wind_gust_ms else None,
            "wind_direction": self.wind_direction_10m,
            "wind_direction_text": self._wind_dir_to_text(self.wind_direction_10m),
            "visibility": round(self.visibility_km, 1),
            "precipitation": self.precipitation,
            "rain": self.rain,
            "snowfall": self.snowfall,
            "cloud_cover": self.cloud_cover,
            "cloud_ceiling": self.cloud_ceiling,
            "weather_code": self.weather_code,
            "weather_text": self.weather_text
        }
    
    @staticmethod
    def _wind_dir_to_text(degree: int) -> str:
        """风向角度转文字"""
        directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
        index = round(degree / 45) % 8
        return directions[index]


class OpenMeteoClient:
    """Open-Meteo API客户端"""
    
    def __init__(self, base_url: str = "https://api.open-meteo.com/v1",
                 geocoding_url: str = "https://geocoding-api.open-meteo.com/v1"):
        self.base_url = base_url
        self.geocoding_url = geocoding_url
        self.client = httpx.AsyncClient(timeout=30.0)
    
    # 中文常见地名 → 城市级名称映射（Open-Meteo geocoding 对细粒度地名支持差）
    LOCATION_ALIAS = {
        # 深圳
        "深圳湾公园": "深圳", "深圳人才公园": "深圳",
        "深圳湾": "深圳", "人才公园": "深圳",
        "南山区": "深圳", "福田区": "深圳",
        "宝安区": "深圳", "龙岗区": "深圳", "罗湖区": "深圳",
        "龙华区": "深圳", "光明区": "深圳", "盐田区": "深圳",
        "坪山区": "深圳", "前海": "深圳",
        "莲花山公园": "深圳", "中心公园": "深圳",
        "南山": "深圳", "福田": "深圳", "宝安": "深圳",
        "龙岗": "深圳", "罗湖": "深圳", "龙华": "深圳",
        "光明": "深圳", "盐田": "深圳", "坪山": "深圳",
        # 广州
        "天河": "广州", "天河区": "广州", "越秀区": "广州",
        "番禺区": "广州", "白云区": "广州", "海珠区": "广州",
        "黄埔区": "广州", "花都区": "广州", "增城": "广州",
        "花城广场": "广州", "白云山": "广州", "越秀公园": "广州",
        # 北京
        "国贸": "北京", "CBD": "北京", "朝阳区": "北京",
        "海淀区": "北京", "西城区": "北京", "东城区": "北京",
        "丰台区": "北京", "通州区": "北京", "大兴区": "北京",
        "顺义区": "北京", "昌平": "北京",
        "奥林匹克公园": "北京", "颐和园": "北京", "天坛": "北京", "故宫": "北京",
        "朝阳": "北京", "海淀": "北京", "西城": "北京", "东城": "北京",
        "丰台": "北京", "通州": "北京", "大兴": "北京", "顺义": "北京",
        # 上海
        "浦东": "上海", "陆家嘴": "上海", "浦东新区": "上海",
        "徐汇区": "上海", "静安区": "上海", "黄浦区": "上海",
        "虹口区": "上海", "杨浦区": "上海", "闵行区": "上海",
        "松江": "上海", "嘉定": "上海",
        "外滩": "上海", "世纪公园": "上海", "徐家汇": "上海",
        "徐汇": "上海", "静安": "上海", "黄浦": "上海",
        "虹口": "上海", "杨浦": "上海", "闵行": "上海",
        # 杭州
        "西湖": "杭州", "西湖区": "杭州", "余杭区": "杭州",
        "滨江区": "杭州", "萧山区": "杭州", "拱墅区": "杭州",
        "西溪湿地": "杭州",
        "余杭": "杭州", "滨江": "杭州", "萧山": "杭州", "拱墅": "杭州",
        # 成都
        "武侯区": "成都", "锦江区": "成都", "高新区": "成都",
        "天府新区": "成都", "青羊区": "成都",
        "武侯": "成都", "锦江": "成都", "高新": "成都", "天府": "成都", "青羊": "成都",
        "宽窄巷子": "成都", "锦里": "成都",
        # 南京
        "鼓楼区": "南京", "建邺区": "南京", "玄武区": "南京",
        "江宁区": "南京",
        "鼓楼": "南京", "建邺": "南京", "玄武": "南京", "江宁": "南京",
        "夫子庙": "南京", "中山陵": "南京",
        # 武汉
        "武昌": "武汉", "汉口": "武汉", "汉阳": "武汉",
        "洪山区": "武汉", "江汉区": "武汉",
        "洪山": "武汉", "江汉": "武汉",
        "东湖": "武汉", "黄鹤楼": "武汉",
    }

    async def geocode(self, location: str) -> Optional[Dict]:
        """
        地理编码：地名 -> 经纬度（带多级降级策略）
        
        降级顺序：
        1. 原始地名（中文）
        2. 别名映射后的地名
        3. 去掉"区/县/市/湾"等后缀
        4. 英文名拼音尝试（仅常见城市）
        
        Args:
            location: 城市名称（如"深圳"、"深圳湾"、"Shenzhen"）
            
        Returns:
            {"latitude": float, "longitude": float, "name": str, "country": str}
        """
        # 构建候选查询列表
        candidates = []
        
        # 1. 别名映射（优先级最高——细粒度地名直接映射到城市级）
        if location in self.LOCATION_ALIAS:
            candidates.append(self.LOCATION_ALIAS[location])
        
        # 2. 原始名称
        candidates.append(location)
        
        # 3. 去掉常见后缀/前缀，提取核心地名
        suffixes = ["湾", "区", "县", "市", "镇", "村", "街道", "新区", "高新区",
                    "公园", "广场", "景区", "大桥", "机场", "火车站", "高铁站"]
        stripped = location
        for suffix in suffixes:
            if stripped.endswith(suffix) and len(stripped) > len(suffix) + 1:
                stripped = stripped[:-len(suffix)]
                candidates.append(stripped)
                break
        
        # 3.5 从地名中提取已知城市名（如"深圳人才公园"→"深圳"）
        known_cities = [
            "深圳", "广州", "北京", "上海", "杭州", "成都", "武汉", "南京",
            "重庆", "西安", "长沙", "青岛", "天津", "苏州", "郑州",
            "厦门", "福州", "合肥", "昆明", "贵阳", "南宁", "海口",
            "三亚", "珠海", "东莞", "佛山", "无锡", "宁波", "温州",
        ]
        for city in known_cities:
            if city in location and city != location:
                candidates.append(city)
                break
        
        # 4. 常见城市英文名
        en_names = {
            "深圳": "Shenzhen", "广州": "Guangzhou", "北京": "Beijing",
            "上海": "Shanghai", "杭州": "Hangzhou", "成都": "Chengdu",
            "武汉": "Wuhan", "南京": "Nanjing", "重庆": "Chongqing",
            "西安": "Xi'an", "长沙": "Changsha", "青岛": "Qingdao",
            "天津": "Tianjin", "苏州": "Suzhou", "郑州": "Zhengzhou",
        }
        for candidate in list(candidates):
            if candidate in en_names:
                candidates.append(en_names[candidate])
        
        # 依次尝试
        seen = set()
        for name in candidates:
            if name in seen:
                continue
            seen.add(name)
            
            try:
                result = await self._geocode_single(name)
                if result:
                    if name != location:
                        logger.info(f"地理编码降级: '{location}' → '{name}'")
                    return result
            except Exception as e:
                logger.debug(f"尝试'{name}'失败: {e}")
                continue
        
        logger.warning(f"所有候选名称均失败: {candidates}")
        return None

    async def _geocode_single(self, name: str) -> Optional[Dict]:
        """单次地理编码请求"""
        resp = await self.client.get(
            f"{self.geocoding_url}/search",
            params={"name": name, "count": 3, "language": "zh"}
        )
        resp.raise_for_status()
        data = resp.json()
        
        if not data.get("results"):
            return None
        
        # 优先选中国的结果
        results = data["results"]
        cn_results = [r for r in results if r.get("country") == "中国"]
        result = cn_results[0] if cn_results else results[0]
        
        return {
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "name": result.get("name", name),
            "country": result.get("country", ""),
            "admin1": result.get("admin1", ""),
            "timezone": result.get("timezone", "Asia/Shanghai")
        }
    
    async def get_hourly_forecast(
        self,
        latitude: float,
        longitude: float,
        hours: int = 72,
        timezone: str = "auto"
    ) -> List[HourlyWeatherData]:
        """
        获取逐小时预报
        
        Args:
            latitude: 纬度
            longitude: 经度
            hours: 预报时长（小时）
            timezone: 时区
            
        Returns:
            逐小时预报数据列表
        """
        try:
            # Open-Meteo API参数
            # 计算天数（最少1天，最多7天）
            days = max(1, min(7, (hours + 23) // 24))

            params = {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": ",".join([
                    "temperature_2m",
                    "relative_humidity_2m",
                    "wind_speed_10m",
                    "wind_gusts_10m",
                    "wind_direction_10m",
                    "visibility",
                    "precipitation",
                    "rain",
                    "snowfall",
                    "weather_code",
                    "cloud_cover"
                ]),
                "timezone": timezone,
                "forecast_days": days,
            }
            
            resp = await self.client.get(f"{self.base_url}/forecast", params=params)
            resp.raise_for_status()
            data = resp.json()
            
            # 解析数据
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            
            forecasts = []
            for i in range(len(times)):
                forecast = HourlyWeatherData(
                    time=times[i],
                    temperature_2m=hourly.get("temperature_2m", [None])[i] or 0,
                    relative_humidity_2m=hourly.get("relative_humidity_2m", [None])[i] or 0,
                    wind_speed_10m=hourly.get("wind_speed_10m", [None])[i] or 0,
                    wind_gusts_10m=hourly.get("wind_gusts_10m", [None])[i],
                    wind_direction_10m=hourly.get("wind_direction_10m", [None])[i] or 0,
                    visibility=hourly.get("visibility", [None])[i],
                    precipitation=hourly.get("precipitation", [None])[i] or 0,
                    rain=hourly.get("rain", [None])[i] or 0,
                    snowfall=hourly.get("snowfall", [None])[i] or 0,
                    weather_code=hourly.get("weather_code", [None])[i] or 0,
                    cloud_cover=hourly.get("cloud_cover", [None])[i] or 0,
                    cloud_ceiling=None  # 免费API不支持云底高度
                )
                forecasts.append(forecast)
            
            logger.info(f"成功获取{len(forecasts)}小时预报 "
                       f"(lat={latitude}, lon={longitude})")
            return forecasts
            
        except httpx.HTTPStatusError as e:
            logger.error(f"API返回错误: {e.response.status_code} - {e.response.text}")
            raise Exception(f"气象API返回错误: {e.response.status_code}")
        except Exception as e:
            logger.error(f"获取预报失败: {e}")
            raise Exception(f"获取气象数据失败: {e}")
    
    async def get_forecast_by_location(
        self,
        location: str,
        hours: int = 72
    ) -> Dict:
        """
        通过地名获取预报（自动地理编码）
        
        Args:
            location: 城市名称
            hours: 预报时长
            
        Returns:
            {"location": dict, "forecasts": list}
        """
        # 1. 地理编码
        geo = await self.geocode(location)
        if not geo:
            raise Exception(f"无法找到地点「{location}」，请尝试使用城市名称（如：深圳、北京、上海）")
        
        # 2. 获取预报
        forecasts = await self.get_hourly_forecast(
            geo["latitude"],
            geo["longitude"],
            hours=hours,
            timezone=geo.get("timezone", "auto")
        )
        
        return {
            "location": geo,
            "forecasts": forecasts
        }
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


if __name__ == "__main__":
    """测试API"""
    import asyncio
    
    async def test():
        client = OpenMeteoClient()
        
        # 测试地理编码
        geo = await client.geocode("深圳")
        print(f"地理编码: {geo}")
        
        if geo:
            # 测试预报
            forecasts = await client.get_hourly_forecast(
                geo["latitude"], geo["longitude"], hours=12
            )
            print(f"\n获取{len(forecasts)}小时预报:")
            for f in forecasts:
                print(f"  {f.time} | {f.temperature_2m:.1f}℃ | "
                      f"风{f.wind_speed_10m:.1f}km/h | "
                      f"能见度{f.visibility_km:.1f}km | {f.weather_text}")
        
        await client.close()
    
    asyncio.run(test())
