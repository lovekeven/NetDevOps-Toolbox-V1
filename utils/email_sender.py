# 导入模块，初始项目根路径
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
# 导入日志器
from utils.log_setup import setup_logger

logger = setup_logger("email_sender.py", "email_sender.log")
# 导入smtplib模块与邮件服务器建立连接,登录验证
import smtplib

# 导入生成正文对象的工具包
from email.mime.text import MIMEText

# 导入生成信封的工具包
from email.mime.multipart import MIMEMultipart

# 导入时间模块
from datetime import datetime


class EmailSender:
    def __init__(self, smtp_server, smtp_port, smtp_email, smtp_password):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_email = smtp_email
        self.smtp_password = smtp_password
        logger.info("与邮件服务器连接初始化完成")

    # 核心方法
    def ai_report_to_email(self, ai_report, recipient_emails, report_type=None):
        # 尝试封装正文对象建立连接
        try:
            msg = MIMEMultipart("alternative")  # 信封支持多种格式的转换
            # 先写邮件主题
            msg["Subject"] = (
                f"Netdevops运维工具箱：关于设备的AI{report_type}状态分析 --{datetime.now().strftime('%Y年-%M月-%d日 %H:%M:%S')}"
            )
            msg["From"] = self.smtp_email
            msg["To"] = ", ".join(recipient_emails)
            # 1.邮件服务器规范：多个收件人邮箱必须用「英文逗号 + 空格」分隔（如a@163.com, b@qq.com）
            # 2. 生成HTML格式正文（主流邮箱支持，保留AI排版，更美观）
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: 微软雅黑, Arial, sans-serif; line-height: 1.8; color: #333; padding: 20px; }}
                    h2 {{ color: #2c3e50; border-left: 4px solid #3498db; padding-left: 10px; margin-bottom: 20px; }}
                    .generate-time {{ color: #666; font-size: 14px; margin-bottom: 15px; }}
                    .report-content {{ white-space: pre-wrap; word-wrap: break-word; margin: 20px 0; line-height: 2.0; }}
                    hr {{ border: 0; border-top: 1px solid #eee; margin: 30px 0; }}
                    .footer {{ color: #999; font-size: 12px; text-align: right; margin-top: 30px; }}
                </style>
            </head>
            <body>
                <h2>📋 设备{report_type}AI分析报告</h2>
                <p class="generate-time"><strong>生成时间：</strong>{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
                <hr>
                <!-- AI生成的报告内容，直接展示，保留所有原有排版 -->
                <div class="report-content">{ai_report}</div>
                <hr>
                <p class="footer">此邮件由NetDevOps自动化运维平台自动发送 | 无需回复</p>
            </body>
            </html>
            """

            # 3. 生成纯文本格式正文（备用，防止极少数邮箱不支持HTML）
            text_content = f"""
【设备{report_type}AI分析报告】
生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
——————————————————
{ai_report}
——————————————————
此邮件为自动化平台自动发送，无需回复
"""
            # 把正文对象装进信封
            # 正文内容直接传变量
            msg.attach(MIMEText(html_content, "html", "utf-8"))
            msg.attach(MIMEText(text_content, "plain", "utf-8"))
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                # 建立安全连接
                server.login(self.smtp_email, self.smtp_password)
                server.send_message(msg=msg)
            for recent in recipient_emails:
                logger.info(f"设备{report_type}AI分析报告已经成功放送到{recent}邮箱")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"设备{report_type}AI分析报告发送邮箱失败,错误原因：{error_msg}")
            raise
