"""
任务分析与研判模块
理解用户需求，完成专业研判任务并给出决策建议
"""
import re
import yaml
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import logging

from .weather_api import HourlyWeatherData

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """风险等级"""
    SAFE = "safe"           # 安全-可执行
    CAUTION = "caution"     # 谨慎-需注意
    RISKY = "risky"         # 风险-建议调整
    FORBIDDEN = "forbidden" # 禁止-不可执行


@dataclass
class TimeSlotAssessment:
    """单个时段评估结果"""
    start_time: datetime
    end_time: datetime
    risk_level: RiskLevel
    score: float                 # 0-100，飞行适宜度评分
    can_fly: bool
    issues: List[str]            # 致命问题
    warnings: List[str]          # 警告信息
    suggestions: List[str]       # 操作建议
    weather_summary: str         # 天气概况


@dataclass
class TaskAssessmentResult:
    """完整任务评估结果"""
    task_description: str        # 任务描述
    location: str                # 地点
    requested_window: str        # 用户请求的时段
    overall_risk: RiskLevel      # 整体风险等级
    recommendation: str          # 总体建议
    slot_assessments: List[TimeSlotAssessment]  # 各时段评估
    best_window: Optional[str]   # 最佳飞行窗口
    data_source: str             # 数据来源
    data_time: str               # 数据获取时间
    raw_forecast: List[dict]     # 原始预报数据


class DroneTaskAnalyzer:
    """无人机任务分析器"""
    
    def __init__(self, config_path: str = "backend/config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        self.rules = self.config['flight_rules']
        self.prohibited_weather = self.rules['prohibited_weather']
    
    def parse_user_request(self, user_input: str) -> Dict:
        """
        解析用户需求
        
        支持格式:
        - "明早6-9点深圳湾适合无人机巡检吗"
        - "明天下午2-5点北京国贸能飞无人机吗"
        - "今天10-12点上海浦东适合飞行吗"
        - "后天早上深圳适合飞吗"
        
        Returns:
            {"location": str, "start_hour": int, "end_hour": int, "date": str}
        """
        result = {
            "location": "",
            "start_hour": 0,
            "end_hour": 0,
            "date": "today",  # today/tomorrow/day_after
            "task_type": "巡检",
            "raw_query": user_input
        }
        
        # 解析地点（常见城市+地标+公园，长名称优先匹配）
        cities = [
            # 深圳（含地标/公园）
            "深圳人才公园", "深圳湾公园", "深圳湾", "深圳",
            "南山", "福田", "宝安", "龙岗", "罗湖",
            "龙华", "光明", "盐田", "坪山", "前海",
            "人才公园", "莲花山公园", "中心公园",
            # 广州
            "天河", "番禺", "白云", "海珠", "黄埔", "花都", "增城", "广州",
            "花城广场", "白云山", "越秀公园",
            # 北京
            "国贸", "朝阳", "海淀", "西城", "东城", "丰台", "通州",
            "大兴", "顺义", "昌平", "北京",
            "奥林匹克公园", "颐和园", "天坛", "故宫",
            # 上海
            "陆家嘴", "浦东", "徐汇", "静安", "黄浦", "虹口", "杨浦",
            "闵行", "松江", "嘉定", "上海",
            "外滩", "世纪公园", "徐家汇",
            # 杭州
            "西湖", "余杭", "滨江", "萧山", "拱墅", "杭州",
            "西溪湿地",
            # 成都
            "武侯", "锦江", "高新", "天府", "青羊", "成都",
            "宽窄巷子", "锦里",
            # 南京
            "鼓楼", "建邺", "玄武", "江宁", "南京",
            "夫子庙", "中山陵",
            # 武汉
            "武昌", "汉口", "汉阳", "洪山", "江汉", "武汉",
            "东湖", "黄鹤楼",
            # 其他城市
            "重庆", "西安", "长沙", "青岛", "天津", "苏州", "郑州",
            "厦门", "福州", "合肥", "昆明", "贵阳", "南宁", "海口",
            "三亚", "珠海", "东莞", "佛山", "无锡", "宁波", "温州",
        ]
        for city in cities:
            if city in user_input:
                result["location"] = city
                break
        
        # 如果没找到具体城市，尝试提取地名
        if not result["location"]:
            # 策略1: 提取"点/在"后面的地名
            match = re.search(r'(?:点|在)\s*([\u4e00-\u9fa5]{2,6}?)(?:适合|能飞|可以飞|飞行)', user_input)
            if match:
                result["location"] = match.group(1)
            else:
                # 策略2: 提取时间后面的地名
                match = re.search(r'(?:点|时)\s*([\u4e00-\u9fa5]{2,6})', user_input)
                if match:
                    result["location"] = match.group(1)
                else:
                    # 策略3: 提取"适合/能飞"前面的地名
                    match = re.search(r'([\u4e00-\u9fa5]{2,6}?)(?:适合|能飞|可以飞|飞行)', user_input)
                    if match:
                        candidate = match.group(1)
                        # 排除常见非地名词
                        exclude = ["无人机", "飞行", "巡检", "航拍", "今天", "明天", "后天",
                                   "早上", "上午", "下午", "晚上", "早晨"]
                        if candidate not in exclude:
                            result["location"] = candidate
        
        # 解析时间
        # 判断是否有"下午/晚上"前缀（用于数字时间偏移）
        has_afternoon = any(kw in user_input for kw in ["下午", "傍晚"])
        has_evening = "晚上" in user_input or "夜间" in user_input
        time_offset = 12 if (has_afternoon or has_evening) else 0
        
        # 格式1: "下午3点到6点" / "3-6点" / "3点到6点"
        time_match = re.search(r'(\d{1,2})\s*点?\s*[-到至~]\s*(\d{1,2})\s*点', user_input)
        if time_match:
            start_h = int(time_match.group(1))
            end_h = int(time_match.group(2))
            # 如果带"下午"前缀且数字<12，加12小时
            if time_offset and start_h < 12:
                start_h += time_offset
                end_h += time_offset
            # 如果带"晚上"前缀且数字<8，加12小时
            if has_evening and start_h < 8:
                start_h += 12
                end_h += 12
            result["start_hour"] = start_h
            result["end_hour"] = end_h
        else:
            # 格式2: "早上" / "上午" / "下午" / "晚上"（无具体数字）
            if "早上" in user_input or "早晨" in user_input or "明早" in user_input:
                result["start_hour"] = 6
                result["end_hour"] = 9
            elif "上午" in user_input:
                result["start_hour"] = 8
                result["end_hour"] = 12
            elif "下午" in user_input:
                result["start_hour"] = 13
                result["end_hour"] = 17
            elif "晚上" in user_input or "夜间" in user_input:
                result["start_hour"] = 18
                result["end_hour"] = 21
            else:
                # 默认白天
                result["start_hour"] = 8
                result["end_hour"] = 18
        
        # 解析日期
        weekday_map = {
            "周一": 0, "星期二": 1, "周三": 2, "星期三": 2,
            "周四": 3, "星期四": 3, "周五": 4, "星期五": 4,
            "周六": 5, "星期六": 5, "周日": 6, "星期日": 6, "星期天": 6,
        }
        if "明天" in user_input or "明早" in user_input or "明日" in user_input:
            result["date"] = "tomorrow"
        elif "后天" in user_input:
            result["date"] = "day_after"
        elif "今天" in user_input or "今日" in user_input:
            result["date"] = "today"
        else:
            # 尝试匹配"周X"
            matched_weekday = False
            for day_name, day_num in weekday_map.items():
                if day_name in user_input:
                    result["date"] = f"weekday_{day_num}"
                    matched_weekday = True
                    break
            if not matched_weekday:
                # 默认明天
                result["date"] = "tomorrow"
        
        # 解析任务类型（扩充：支持户外活动等通用场景）
        task_types = {
            "巡检": ["巡检", "巡查", "检查"],
            "航拍": ["航拍", "拍摄", "录像", "拍照"],
            "测绘": ["测绘", "测量", "勘探"],
            "植保": ["植保", "喷洒", "农药", "施肥"],
            "配送": ["配送", "送货", "运输", "快递"],
            "应急": ["应急", "救援", "搜救"],
            "户外活动": ["户外活动", "活动", "运动会", "庆典", "演出", "集会", "游园"],
            "飞行": ["飞行", "飞无人机", "能飞", "适合飞"]
        }
        for task_type, keywords in task_types.items():
            if any(kw in user_input for kw in keywords):
                result["task_type"] = task_type
                break
        
        return result
    
    def assess_time_slot(
        self,
        forecasts: List[HourlyWeatherData],
        start_hour: int,
        end_hour: int,
        target_date: Optional[datetime] = None,
        drone_type: str = "consumer"
    ) -> List[TimeSlotAssessment]:
        """
        评估每个小时的飞行条件
        
        Args:
            forecasts: 逐小时预报
            start_hour: 起始小时
            end_hour: 结束小时
            target_date: 目标日期
            drone_type: 无人机类型 (consumer/industrial)
            
        Returns:
            每个时段的评估结果列表
        """
        drone_rules = self.rules['drone_types'].get(drone_type, self.rules['drone_types']['consumer'])
        max_wind = drone_rules['max_wind']
        
        results = []
        
        for forecast in forecasts:
            hour = forecast.datetime_obj.hour
            
            # 如果指定了日期，过滤日期
            if target_date and forecast.datetime_obj.date() != target_date.date():
                continue
            
            # 检查是否在时间窗口内
            if not (start_hour <= hour < end_hour):
                continue
            
            assessment = self._assess_single_hour(forecast, max_wind)
            results.append(assessment)
        
        return results
    
    def _assess_single_hour(
        self,
        forecast: HourlyWeatherData,
        max_wind: float
    ) -> TimeSlotAssessment:
        """评估单个小时"""
        issues = []
        warnings = []
        suggestions = []
        score = 100.0
        
        # 1. 风速评估
        wind_score, wind_issues, wind_warnings = self._check_wind(forecast, max_wind)
        score += wind_score
        issues.extend(wind_issues)
        warnings.extend(wind_warnings)
        
        # 2. 能见度评估
        vis_score, vis_issues, vis_warnings = self._check_visibility(forecast)
        score += vis_score
        issues.extend(vis_issues)
        warnings.extend(vis_warnings)
        
        # 3. 降水评估
        precip_score, precip_issues, precip_warnings = self._check_precipitation(forecast)
        score += precip_score
        issues.extend(precip_issues)
        warnings.extend(precip_warnings)
        
        # 4. 温度评估
        temp_score, temp_issues, temp_warnings = self._check_temperature(forecast)
        score += temp_score
        issues.extend(temp_issues)
        warnings.extend(temp_warnings)
        
        # 5. 湿度评估
        humid_score, humid_issues, humid_warnings = self._check_humidity(forecast)
        score += humid_score
        issues.extend(humid_issues)
        warnings.extend(humid_warnings)
        
        # 6. 天气现象评估
        weather_score, weather_issues, weather_warnings = self._check_weather(forecast)
        score += weather_score
        issues.extend(weather_issues)
        warnings.extend(weather_warnings)
        
        # 7. 云底高度评估
        cloud_score, cloud_issues, cloud_warnings = self._check_cloud(forecast)
        score += cloud_score
        issues.extend(cloud_issues)
        warnings.extend(cloud_warnings)
        
        # 归一化评分到0-100
        score = max(0, min(100, score + 100))
        
        # 判定风险等级
        can_fly = len(issues) == 0
        if issues:
            risk_level = RiskLevel.FORBIDDEN
        elif score < 40:
            risk_level = RiskLevel.RISKY
        elif score < 70:
            risk_level = RiskLevel.CAUTION
        else:
            risk_level = RiskLevel.SAFE
        
        # 生成建议
        suggestions = self._generate_suggestions(forecast, issues, warnings, risk_level)
        
        # 天气概况
        weather_summary = (
            f"{forecast.weather_text}，"
            f"{forecast.temperature_2m:.0f}℃，"
            f"风速{forecast.wind_speed_ms:.1f}m/s"
            f"{'，阵风'+f'{forecast.wind_gust_ms:.1f}m/s' if forecast.wind_gust_ms else ''}，"
            f"能见度{forecast.visibility_km:.1f}km，"
            f"湿度{forecast.relative_humidity_2m}%"
        )
        
        start = forecast.datetime_obj
        end = start + timedelta(hours=1)
        
        return TimeSlotAssessment(
            start_time=start,
            end_time=end,
            risk_level=risk_level,
            score=round(score, 1),
            can_fly=can_fly,
            issues=issues,
            warnings=warnings,
            suggestions=suggestions,
            weather_summary=weather_summary
        )
    
    def _check_wind(self, f: HourlyWeatherData, max_wind: float) -> Tuple[float, List[str], List[str]]:
        """检查风速"""
        issues, warnings = [], []
        score = 0.0
        safe_wind = 8.0
        
        # 阵风检查
        if f.wind_gust_ms and f.wind_gust_ms > 17.2:
            issues.append(f"阵风{f.wind_gust_ms:.1f}m/s（{self._wind_level(f.wind_gust_ms)}），超过安全极限")
            score -= 50
        elif f.wind_gust_ms and f.wind_gust_ms > 13.9:
            issues.append(f"阵风{f.wind_gust_ms:.1f}m/s（{self._wind_level(f.wind_gust_ms)}），超出抗风能力")
            score -= 30
        elif f.wind_gust_ms and f.wind_gust_ms > safe_wind:
            warnings.append(f"阵风{f.wind_gust_ms:.1f}m/s（{self._wind_level(f.wind_gust_ms)}），需注意")
            score -= 10
        
        # 平均风速检查
        if f.wind_speed_ms > max_wind:
            issues.append(f"平均风速{f.wind_speed_ms:.1f}m/s（{self._wind_level(f.wind_speed_ms)}），超限")
            score -= 40
        elif f.wind_speed_ms > safe_wind:
            warnings.append(f"风速{f.wind_speed_ms:.1f}m/s（{self._wind_level(f.wind_speed_ms)}），接近上限")
            score -= 15
        else:
            score += 10
        
        return score, issues, warnings
    
    def _check_visibility(self, f: HourlyWeatherData) -> Tuple[float, List[str], List[str]]:
        """检查能见度"""
        issues, warnings = [], []
        score = 0.0
        
        min_vis = self.rules['visibility']['minimum']
        good_vis = self.rules['visibility']['good']
        
        if f.visibility_km < min_vis:
            issues.append(f"能见度{f.visibility_km:.1f}km，低于最低要求{min_vis}km，无法保证视距内飞行安全")
            score -= 40
        elif f.visibility_km < good_vis:
            warnings.append(f"能见度{f.visibility_km:.1f}km，未达良好标准{good_vis}km")
            score -= 10
        else:
            score += 10
        
        return score, issues, warnings
    
    def _check_precipitation(self, f: HourlyWeatherData) -> Tuple[float, List[str], List[str]]:
        """检查降水"""
        issues, warnings = [], []
        score = 0.0
        
        max_precip = self.rules['precipitation']['max_intensity']
        
        if f.precipitation > max_precip:
            issues.append(f"降水量{f.precipitation:.1f}mm/h，无人机不可在雨中飞行")
            score -= 50
        elif f.precipitation > 0:
            issues.append(f"有降水{f.precipitation:.1f}mm/h，不满足飞行条件")
            score -= 30
        else:
            score += 5
        
        return score, issues, warnings
    
    def _check_temperature(self, f: HourlyWeatherData) -> Tuple[float, List[str], List[str]]:
        """检查温度"""
        issues, warnings = [], []
        score = 0.0
        
        temp_rules = self.rules['temperature']
        
        if f.temperature_2m < temp_rules['min']:
            issues.append(f"温度{f.temperature_2m:.0f}℃，低于电池工作下限{temp_rules['min']}℃")
            score -= 40
        elif f.temperature_2m > temp_rules['max']:
            issues.append(f"温度{f.temperature_2m:.0f}℃，超过电子元件上限{temp_rules['max']}℃")
            score -= 40
        elif f.temperature_2m < temp_rules['optimal_min']:
            warnings.append(f"温度{f.temperature_2m:.0f}℃偏低，电池续航将缩短约30%")
            score -= 10
        elif f.temperature_2m > temp_rules['optimal_max']:
            warnings.append(f"温度{f.temperature_2m:.0f}℃偏高，注意电机散热")
            score -= 5
        else:
            score += 5
        
        return score, issues, warnings
    
    def _check_humidity(self, f: HourlyWeatherData) -> Tuple[float, List[str], List[str]]:
        """检查湿度"""
        issues, warnings = [], []
        score = 0.0
        
        max_humidity = self.rules['humidity']['max']
        warn_humidity = self.rules['humidity']['warning']
        
        if f.relative_humidity_2m > max_humidity:
            issues.append(f"湿度{f.relative_humidity_2m}%，超过{max_humidity}%，有结露风险")
            score -= 30
        elif f.relative_humidity_2m > warn_humidity:
            warnings.append(f"湿度{f.relative_humidity_2m}%，较高，注意设备防潮")
            score -= 5
        else:
            score += 5
        
        return score, issues, warnings
    
    def _check_weather(self, f: HourlyWeatherData) -> Tuple[float, List[str], List[str]]:
        """检查天气现象"""
        issues, warnings = [], []
        score = 0.0
        
        # 检查禁止飞行的天气
        weather_text_en = f.weather_text  # 用原始WMO code判断更准确
        prohibited_cn = {
            95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
            65: "大雨", 67: "大冻雨",
            75: "大雪", 86: "大阵雪",
            82: "大阵雨"
        }
        
        for code, text in prohibited_cn.items():
            if f.weather_code == code:
                issues.append(f'当前天气「{text}」，属于禁止飞行条件')
                score -= 50
                break
        
        # 雾（WMO 45, 48）
        if f.weather_code in [45, 48]:
            issues.append(f"有雾，能见度可能不足1km")
            score -= 30
        
        if not issues:
            score += 5
        
        return score, issues, warnings
    
    def _check_cloud(self, f: HourlyWeatherData) -> Tuple[float, List[str], List[str]]:
        """检查云底高度"""
        issues, warnings = [], []
        score = 0.0
        
        if f.cloud_ceiling is not None:
            min_ceiling = self.rules['cloud_ceiling']['minimum']
            if f.cloud_ceiling < min_ceiling:
                warnings.append(f"云底高度{f.cloud_ceiling:.0f}m，低于{min_ceiling}m")
                score -= 10
            else:
                score += 5
        else:
            # 用云量估算
            if f.cloud_cover > 90:
                warnings.append(f"云量{f.cloud_cover}%，天空阴沉")
                score -= 5
            else:
                score += 5
        
        return score, issues, warnings
    
    def _wind_level(self, speed_ms: float) -> str:
        """风速转蒲福风级"""
        levels = [
            (0.3, "1级"), (1.6, "2级"), (3.4, "3级"), (5.5, "4级"),
            (8.0, "5级"), (10.8, "6级"), (13.9, "7级"), (17.2, "8级"),
            (20.8, "9级"), (24.5, "10级")
        ]
        for threshold, level in levels:
            if speed_ms <= threshold:
                return level
        return "11级以上"
    
    def _generate_suggestions(
        self,
        forecast: HourlyWeatherData,
        issues: List[str],
        warnings: List[str],
        risk_level: RiskLevel
    ) -> List[str]:
        """生成操作建议"""
        suggestions = []
        
        if risk_level == RiskLevel.FORBIDDEN:
            suggestions.append("⛔ 该时段不建议飞行，建议调整任务时间")
        elif risk_level == RiskLevel.RISKY:
            suggestions.append("⚠️ 飞行条件较差，建议：")
            if any("风" in i for i in issues + warnings):
                suggestions.append("  - 降低飞行高度，减小迎风面")
                suggestions.append("  - 缩短飞行距离，保持目视范围")
            if any("温度" in w for w in warnings):
                suggestions.append("  - 多备电池，低温续航缩短")
            if any("能见度" in i for i in issues + warnings):
                suggestions.append("  - 开启避障系统，降低飞行速度")
        elif risk_level == RiskLevel.CAUTION:
            suggestions.append("✅ 可飞行，建议注意以下事项：")
            for w in warnings:
                if "风" in w:
                    suggestions.append("  - 留意风向变化，选择避风路线")
                if "温度" in w:
                    suggestions.append("  - 关注电池状态，低温环境提前预热")
                if "湿度" in w:
                    suggestions.append("  - 飞行前后检查设备是否有凝露")
        else:
            suggestions.append("✅ 飞行条件良好，正常执行任务即可")
        
        # 通用建议
        if forecast.wind_speed_ms > 5:
            suggestions.append("  - 起飞后先悬停30秒，确认姿态稳定")
        if forecast.temperature_2m < 5:
            suggestions.append("  - 起飞前电池预热至15℃以上")
        
        return suggestions
    
    def generate_full_assessment(
        self,
        user_input: str,
        forecasts: List[HourlyWeatherData],
        location_info: Dict
    ) -> TaskAssessmentResult:
        """
        生成完整任务评估报告
        
        Args:
            user_input: 用户原始输入
            forecasts: 逐小时预报数据
            location_info: 地点信息
            
        Returns:
            TaskAssessmentResult
        """
        # 1. 解析用户需求
        request = self.parse_user_request(user_input)
        
        # 2. 确定目标日期
        now = datetime.now()
        date_str = request["date"]
        if date_str == "tomorrow":
            target_date = now + timedelta(days=1)
        elif date_str == "day_after":
            target_date = now + timedelta(days=2)
        elif date_str.startswith("weekday_"):
            # 计算下一个指定星期几
            target_weekday = int(date_str.split("_")[1])
            days_ahead = target_weekday - now.weekday()
            if days_ahead <= 0:  # 已经过了，取下周
                days_ahead += 7
            target_date = now + timedelta(days=days_ahead)
        else:
            target_date = now
        
        # 3. 评估各时段
        slot_assessments = self.assess_time_slot(
            forecasts,
            request["start_hour"],
            request["end_hour"],
            target_date
        )
        
        # 4. 找出最佳窗口
        flyable_slots = [s for s in slot_assessments if s.can_fly]
        best_window = None
        if flyable_slots:
            # 找连续可飞时段
            best = max(flyable_slots, key=lambda x: x.score)
            best_window = f"{best.start_time.strftime('%H:%M')}-{(best.end_time).strftime('%H:%M')}"
        
        # 5. 综合评估
        if not slot_assessments:
            overall_risk = RiskLevel.FORBIDDEN
            recommendation = "未获取到目标时段的预报数据"
        elif not flyable_slots:
            overall_risk = RiskLevel.FORBIDDEN
            recommendation = f"请求时段（{request['start_hour']}:00-{request['end_hour']}:00）全部不满足飞行条件"
        elif len(flyable_slots) == len(slot_assessments):
            overall_risk = RiskLevel.SAFE
            recommendation = f"请求时段全部满足飞行条件"
        else:
            flyable_ratio = len(flyable_slots) / len(slot_assessments)
            if flyable_ratio >= 0.7:
                overall_risk = RiskLevel.CAUTION
            else:
                overall_risk = RiskLevel.RISKY
            
            flyable_hours = [f"{s.start_time.strftime('%H:%M')}" for s in flyable_slots]
            recommendation = f"请求时段中{len(flyable_slots)}/{len(slot_assessments)}小时可飞行，建议{best_window}窗口执行"
        
        # 6. 格式化请求时段
        date_str = target_date.strftime("%m月%d日")
        requested_window = f"{date_str} {request['start_hour']}:00-{request['end_hour']}:00"
        
        # 7. 原始预报数据（用于前端展示）
        raw_forecast = []
        for f in forecasts:
            if f.datetime_obj.date() == target_date.date():
                raw_forecast.append(f.to_dict())
        
        return TaskAssessmentResult(
            task_description=f"{location_info.get('name', request['location'])} {request['task_type']}任务",
            location=location_info.get('name', request['location']),
            requested_window=requested_window,
            overall_risk=overall_risk,
            recommendation=recommendation,
            slot_assessments=slot_assessments,
            best_window=best_window,
            data_source="Open-Meteo",
            data_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            raw_forecast=raw_forecast
        )
    
    def result_to_dict(self, result: TaskAssessmentResult) -> dict:
        """将结果转为字典（用于API响应）"""
        risk_labels = {
            RiskLevel.SAFE: "安全",
            RiskLevel.CAUTION: "谨慎",
            RiskLevel.RISKY: "风险",
            RiskLevel.FORBIDDEN: "禁止"
        }
        
        risk_colors = {
            RiskLevel.SAFE: "#22c55e",
            RiskLevel.CAUTION: "#eab308",
            RiskLevel.RISKY: "#f97316",
            RiskLevel.FORBIDDEN: "#ef4444"
        }
        
        return {
            "task_description": result.task_description,
            "location": result.location,
            "requested_window": result.requested_window,
            "overall_risk": result.overall_risk.value,
            "overall_risk_label": risk_labels[result.overall_risk],
            "overall_risk_color": risk_colors[result.overall_risk],
            "recommendation": result.recommendation,
            "best_window": result.best_window,
            "data_source": result.data_source,
            "data_time": result.data_time,
            "slot_assessments": [
                {
                    "start_time": s.start_time.strftime("%Y-%m-%d %H:%M"),
                    "end_time": s.end_time.strftime("%H:%M"),
                    "hour": s.start_time.hour,
                    "risk_level": s.risk_level.value,
                    "risk_label": risk_labels[s.risk_level],
                    "risk_color": risk_colors[s.risk_level],
                    "score": s.score,
                    "can_fly": s.can_fly,
                    "issues": s.issues,
                    "warnings": s.warnings,
                    "suggestions": s.suggestions,
                    "weather_summary": s.weather_summary
                }
                for s in result.slot_assessments
            ],
            "raw_forecast": result.raw_forecast
        }
