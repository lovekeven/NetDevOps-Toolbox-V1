from datetime import datetime, timedelta
import pytz
from utils.log_setup import setup_logger  # 新增：统一使用项目日志器

logger = setup_logger("aliyun_time", "aliyun_time.log")  # 新增：初始化日志器

def convert_aliyun_time(aliyun_time_str):
    """把阿里云UTC时间转成北京时间（ISO 8601格式）"""
    if not aliyun_time_str:
        return ""
    try:
        utc_time = datetime.fromisoformat(aliyun_time_str.replace('Z', '+00:00'))
        beijing_tz = pytz.timezone('Asia/Shanghai')
        beijing_time = utc_time.astimezone(beijing_tz)
        return beijing_time.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        # 原代码：print(f"时间转换失败：{e}")  # 问题：使用 print 而不是 logger
        logger.error(f"时间转换失败：{e}")  # 修复：统一使用 logger
        return aliyun_time_str