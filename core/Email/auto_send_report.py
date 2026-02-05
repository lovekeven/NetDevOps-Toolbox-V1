import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
# 引入时间
from datetime import datetime

# 引入日志器
from utils.log_setup import setup_logger

logger = setup_logger("auto_send_report.py", "auto_send_report.log")
# 引入定时发送任务的核心类
# from apscheduler.schedulers.background import BackgroundScheduler

# 引入邮件发送器
from utils.email_sender import EmailSender

# 引入配置文件
from config import emali_config

# 引入调用的Deepseek模型
from core.AI.report_generator import deepseek_assistant

# 邮件发送器初始化
email_sender = EmailSender(**emali_config.SMTP_CONFIG)
# 初始化定时调度器(时区上海，避免时间偏差)
# scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
ALL_BACKUP_REPORT_CACHE = {}
ALL_HEALTH_REPORT_CACHE = {}
# ---------------------- 业务1：自动发送【备份记录AI报告】 ----------------------


def auto_send_backup_report(days=7):
    try:
        global ALL_BACKUP_REPORT_CACHE
        logger.info(f"【自动任务】开始执行：生成近{days}天备份记录AI报告")
        # 1. 调用AI生成报告（和手动接口完全一样的逻辑）
        report_content = deepseek_assistant.get_deepseek_content(days=days)
        # 2. 可选：更新缓存（和手动接口保持一致，方便手动查询）
        cache_key = f"days_{days}"
        ALL_BACKUP_REPORT_CACHE[cache_key] = {
            "report_content": report_content,
            "create_time": datetime.now().timestamp(),
        }
        # 3. 调用公共邮件工具发送（核心复用，只传内容和标题）
        report_title = f"【自动发送】所有设备近{days}天的备份情况AI报告"
        if email_sender.ai_report_to_email(
            ai_report=report_content, report_type=report_title, recipient_emails=emali_config.RECIPIENT_EMAILS
        ):
            logger.info(f"【自动任务】完成：近{days}天备份记录AI报告发送成功,收件人：{emali_config.RECIPIENT_EMAILS}")
        else:
            logger.error(f"【自动任务】失败：近{days}天备份记录AI报告发送失败")
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error(f"【自动任务】异常：生成/发送备份记录AI报告失败，{error_msg}")


# ---------------------- 业务2：自动发送【全网健康AI报告】 ----------------------


def auto_send_all_health_report(days=7):
    try:
        global ALL_HEALTH_REPORT_CACHE
        logger.info(f"【自动任务】开始执行：生成近{days}天全网设备健康AI报告")
        # 1. 调用AI生成报告（替换成你全网健康报告的AI调用函数，比如get_deepseek_all_health）
        report_content = deepseek_assistant.get_deepseek_all_device_health_weekly(days=days)
        # 2. 更新缓存
        cache_key = f"days_{days}"
        ALL_HEALTH_REPORT_CACHE[cache_key] = {
            "report_content": report_content,
            "create_time": datetime.now().timestamp(),
        }
        # 3. 发送邮箱
        report_title = f"【自动发送】全网设备近{days}天的健康检查AI报告"
        if email_sender.ai_report_to_email(
            ai_report=report_content, report_type=report_title, recipient_emails=emali_config.RECIPIENT_EMAILS
        ):
            logger.info(f"【自动任务】完成：近{days}天全网健康AI报告发送成功,收件人：{emali_config.RECIPIENT_EMAILS}")
        else:
            logger.error(f"【自动任务】失败：近{days}天全网健康AI报告发送失败")
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error(f"【自动任务】异常：生成/发送全网健康AI报告失败，{error_msg}")
