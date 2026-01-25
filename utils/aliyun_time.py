from datetime import datetime, timedelta
import pytz

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
        print(f"时间转换失败：{e}")
        return aliyun_time_str