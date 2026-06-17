import os
import sys
import json

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
# 引入时间
from datetime import datetime

# 引入日志器
from utils.log_setup import setup_logger

logger = setup_logger("auto_send_report.py", "auto_send_report.log")

# 引入邮件发送器
from utils.email_sender import EmailSender

# 引入数据库管理器
from db.database import db_manager

# 引入调用的Deepseek模型
from core.AI.report_generator import deepseek_assistant


def load_email_config():
    """从 email_config.json 读取邮箱配置"""
    config_path = os.path.join(ROOT_DIR, 'config', 'email_config.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def get_recipient_emails():
    """获取收件人邮箱列表"""
    emails_setting = db_manager.get_setting('receive_emails', '[]')
    email_list = json.loads(emails_setting)
    return [item['email'] for item in email_list] if email_list else []


# 初始化邮件发送器
email_config = load_email_config()
smtp_config = {
    "smtp_server": email_config.get("smtp_server", "smtp.qq.com"),
    "smtp_port": email_config.get("smtp_port", 587),
    "smtp_email": email_config.get("sender_email", ""),
    "smtp_password": email_config.get("sender_password", ""),
    "sender_name": email_config.get("sender_name", "NetDevOps工具箱"),
}
email_sender = EmailSender(**smtp_config)

ALL_BACKUP_REPORT_CACHE = {}
ALL_HEALTH_REPORT_CACHE = {}

# ---------------------- 业务1：自动发送【备份记录AI报告】 ----------------------


def auto_send_backup_report(days=7):
    try:
        global ALL_BACKUP_REPORT_CACHE
        logger.info(f"【自动任务】开始执行：生成近{days}天备份记录AI报告")

        # 获取收件人邮箱列表
        recipient_emails = get_recipient_emails()
        if not recipient_emails:
            logger.warning("【自动任务】没有配置收件人邮箱，跳过发送")
            return

        # 1. 调用AI生成报告
        report_content = deepseek_assistant.get_deepseek_content(days=days)
        # 2. 更新缓存
        cache_key = f"days_{days}"
        ALL_BACKUP_REPORT_CACHE[cache_key] = {
            "report_content": report_content,
            "create_time": datetime.now().timestamp(),
        }
        # 3. 发送邮件
        report_title = f"【自动发送】所有设备近{days}天的备份情况AI报告"
        email_sender.ai_report_to_email(
            ai_report=report_content, report_type=report_title, recipient_emails=recipient_emails
        )
        logger.info(f"【自动任务】完成：近{days}天备份记录AI报告发送成功,收件人：{recipient_emails}")
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error(f"【自动任务】异常：生成/发送备份记录AI报告失败，{error_msg}")


# ---------------------- 业务2：自动发送【全网健康AI报告】 ----------------------


def auto_send_all_health_report(days=7):
    try:
        global ALL_HEALTH_REPORT_CACHE
        logger.info(f"【自动任务】开始执行：生成近{days}天全网设备健康AI报告")

        # 获取收件人邮箱列表
        recipient_emails = get_recipient_emails()
        if not recipient_emails:
            logger.warning("【自动任务】没有配置收件人邮箱，跳过发送")
            return

        # 1. 调用AI生成报告
        report_content = deepseek_assistant.get_deepseek_all_device_health_weekly(days=days)
        # 2. 更新缓存
        cache_key = f"days_{days}"
        ALL_HEALTH_REPORT_CACHE[cache_key] = {
            "report_content": report_content,
            "create_time": datetime.now().timestamp(),
        }
        # 3. 发送邮件
        report_title = f"【自动发送】全网设备近{days}天的健康检查AI报告"
        email_sender.ai_report_to_email(
            ai_report=report_content, report_type=report_title, recipient_emails=recipient_emails
        )
        logger.info(f"【自动任务】完成：近{days}天全网健康AI报告发送成功,收件人：{recipient_emails}")
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error(f"【自动任务】异常：生成/发送全网健康AI报告失败，{error_msg}")
