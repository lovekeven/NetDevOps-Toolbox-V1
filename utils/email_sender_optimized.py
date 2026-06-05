"""
优化版邮件发送模块
修复安全问题，增强错误处理，支持多种邮件类型
"""

import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import List, Optional, Dict
from dataclasses import dataclass
import html
import re

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from utils.log_setup import setup_logger

logger = setup_logger("email_sender", "email_sender.log")


# ============================================================
# 配置数据类
# ============================================================

@dataclass
class EmailConfig:
    """邮件配置"""
    smtp_server: str
    smtp_port: int
    smtp_email: str
    smtp_password: str
    use_tls: bool = True
    timeout: int = 30


@dataclass
class EmailMessage:
    """邮件消息"""
    subject: str
    content: str
    content_type: str = "html"  # html/plain
    recipients: List[str] = None
    cc: List[str] = None
    bcc: List[str] = None
    attachments: List[str] = None


# ============================================================
# 邮件发送器
# ============================================================

class EmailSender:
    """邮件发送器，支持多种邮件类型和模板"""

    def __init__(self, config: EmailConfig):
        """
        初始化邮件发送器

        Args:
            config: 邮件配置
        """
        self.config = config
        self._validate_config()
        logger.info(f"邮件发送器初始化完成，SMTP服务器: {config.smtp_server}")

    def _validate_config(self):
        """验证配置"""
        if not self.config.smtp_server:
            raise ValueError("SMTP服务器地址不能为空")
        if not self.config.smtp_email:
            raise ValueError("发件人邮箱不能为空")
        if not self.config.smtp_password:
            raise ValueError("邮箱密码不能为空")
        if self.config.smtp_port not in [25, 465, 587]:
            logger.warning(f"非常用SMTP端口: {self.config.smtp_port}")

    def _sanitize_html(self, content: str) -> str:
        """
        清理HTML内容，防止XSS

        Args:
            content: 原始内容

        Returns:
            清理后的HTML内容
        """
        # 转义HTML特殊字符
        content = html.escape(content)

        # 保留换行和空格
        content = content.replace('\n', '<br>')
        content = content.replace('  ', '&nbsp;&nbsp;')

        return content

    def _create_html_template(self, title: str, content: str, report_type: str = "") -> str:
        """
        创建HTML邮件模板

        Args:
            title: 邮件标题
            content: 邮件内容
            report_type: 报告类型

        Returns:
            HTML内容
        """
        # 清理内容防止XSS
        safe_content = self._sanitize_html(content)

        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.8;
            color: #333333;
            padding: 20px;
            max-width: 800px;
            margin: 0 auto;
            background-color: #f5f5f5;
        }}
        .container {{
            background-color: #ffffff;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
            border-radius: 12px 12px 0 0;
            margin: -30px -30px 30px -30px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
            font-weight: 600;
        }}
        .header .subtitle {{
            font-size: 14px;
            opacity: 0.9;
            margin-top: 5px;
        }}
        .meta-info {{
            background-color: #f8f9fa;
            border-radius: 8px;
            padding: 15px 20px;
            margin-bottom: 25px;
            border-left: 4px solid #667eea;
        }}
        .meta-info p {{
            margin: 5px 0;
            font-size: 14px;
            color: #666;
        }}
        .meta-info strong {{
            color: #333;
        }}
        .content {{
            white-space: pre-wrap;
            word-wrap: break-word;
            line-height: 2.0;
            font-size: 15px;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eeeeee;
            text-align: center;
            color: #999999;
            font-size: 12px;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
        }}
        .badge-success {{
            background-color: #d4edda;
            color: #155724;
        }}
        .badge-warning {{
            background-color: #fff3cd;
            color: #856404;
        }}
        .badge-danger {{
            background-color: #f8d7da;
            color: #721c24;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 NetDevOps 智能运维平台</h1>
            <div class="subtitle">自动化运维报告</div>
        </div>

        <div class="meta-info">
            <p><strong>📋 报告类型：</strong>{report_type or 'AI分析报告'}</p>
            <p><strong>⏰ 生成时间：</strong>{datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}</p>
            <p><strong>🤖 生成方式：</strong>DeepSeek AI 智能分析</p>
        </div>

        <div class="content">{safe_content}</div>

        <div class="footer">
            <p>此邮件由 NetDevOps 自动化运维平台自动发送 | 无需回复</p>
            <p>© {datetime.now().year} NetDevOps Team. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""

    def _create_text_template(self, content: str, report_type: str = "") -> str:
        """
        创建纯文本邮件模板

        Args:
            content: 邮件内容
            report_type: 报告类型

        Returns:
            纯文本内容
        """
        return f"""
【NetDevOps 智能运维平台 - {report_type or 'AI分析报告'}】

生成时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}
生成方式：DeepSeek AI 智能分析

{'='*50}

{content}

{'='*50}

此邮件由 NetDevOps 自动化运维平台自动发送 | 无需回复
© {datetime.now().year} NetDevOps Team. All rights reserved.
"""

    def send_email(self, message: EmailMessage) -> bool:
        """
        发送邮件

        Args:
            message: 邮件消息

        Returns:
            是否发送成功
        """
        try:
            # 创建邮件对象
            msg = MIMEMultipart("alternative")

            # 设置邮件头
            msg["Subject"] = message.subject
            msg["From"] = self.config.smtp_email
            msg["To"] = ", ".join(message.recipients or [])

            if message.cc:
                msg["Cc"] = ", ".join(message.cc)

            # 添加内容
            if message.content_type == "html":
                msg.attach(MIMEText(message.content, "html", "utf-8"))
            else:
                msg.attach(MIMEText(message.content, "plain", "utf-8"))

            # 添加附件
            if message.attachments:
                for filepath in message.attachments:
                    if os.path.exists(filepath):
                        self._attach_file(msg, filepath)
                    else:
                        logger.warning(f"附件不存在: {filepath}")

            # 收集所有收件人
            all_recipients = list(message.recipients or [])
            if message.cc:
                all_recipients.extend(message.cc)
            if message.bcc:
                all_recipients.extend(message.bcc)

            # 发送邮件
            with smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=self.config.timeout) as server:
                if self.config.use_tls:
                    server.starttls()
                server.login(self.config.smtp_email, self.config.smtp_password)
                server.send_message(msg, self.config.smtp_email, all_recipients)

            logger.info(f"邮件发送成功，收件人: {all_recipients}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP认证失败: {e}")
            raise ValueError("邮箱认证失败，请检查邮箱和密码")
        except smtplib.SMTPException as e:
            logger.error(f"SMTP错误: {e}")
            raise
        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            raise

    def _attach_file(self, msg: MIMEMultipart, filepath: str):
        """
        添加附件

        Args:
            msg: 邮件对象
            filepath: 文件路径
        """
        try:
            with open(filepath, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())

            encoders.encode_base64(part)

            filename = os.path.basename(filepath)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename= {filename}"
            )

            msg.attach(part)
            logger.debug(f"添加附件: {filename}")

        except Exception as e:
            logger.warning(f"添加附件失败 {filepath}: {e}")

    # ============================================================
    # 便捷方法
    # ============================================================

    def send_ai_report(
        self,
        ai_report: str,
        recipient_emails: List[str],
        report_type: str = "健康检查"
    ) -> bool:
        """
        发送AI分析报告

        Args:
            ai_report: AI报告内容
            recipient_emails: 收件人邮箱列表
            report_type: 报告类型

        Returns:
            是否发送成功
        """
        subject = f"NetDevOps 运维报告：设备{report_type}AI分析 - {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}"

        # 创建HTML内容
        html_content = self._create_html_template(
            title=f"设备{report_type}AI分析报告",
            content=ai_report,
            report_type=report_type
        )

        # 创建纯文本内容
        text_content = self._create_text_template(
            content=ai_report,
            report_type=report_type
        )

        # 优先发送HTML，纯文本作为备用
        message = EmailMessage(
            subject=subject,
            content=html_content,
            content_type="html",
            recipients=recipient_emails
        )

        return self.send_email(message)

    def send_alert(
        self,
        alert_type: str,
        alert_message: str,
        recipient_emails: List[str],
        device_name: str = ""
    ) -> bool:
        """
        发送告警邮件

        Args:
            alert_type: 告警类型
            alert_message: 告警消息
            recipient_emails: 收件人邮箱列表
            device_name: 设备名称

        Returns:
            是否发送成功
        """
        subject = f"⚠️ NetDevOps 告警：{alert_type} - {device_name or '系统'}"

        content = f"""
告警类型：{alert_type}
设备名称：{device_name or '系统'}
告警时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

告警详情：
{alert_message}

请及时处理！
"""

        html_content = self._create_html_template(
            title="系统告警",
            content=content,
            report_type="告警通知"
        )

        message = EmailMessage(
            subject=subject,
            content=html_content,
            content_type="html",
            recipients=recipient_emails
        )

        return self.send_email(message)

    def send_backup_notification(
        self,
        device_name: str,
        backup_path: str,
        recipient_emails: List[str],
        status: str = "成功"
    ) -> bool:
        """
        发送备份通知

        Args:
            device_name: 设备名称
            backup_path: 备份路径
            recipient_emails: 收件人邮箱列表
            status: 备份状态

        Returns:
            是否发送成功
        """
        subject = f"📦 NetDevOps 备份通知：{device_name} 配置备份{status}"

        content = f"""
设备名称：{device_name}
备份状态：{status}
备份时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
备份路径：{backup_path}
"""

        html_content = self._create_html_template(
            title="备份通知",
            content=content,
            report_type="备份通知"
        )

        message = EmailMessage(
            subject=subject,
            content=html_content,
            content_type="html",
            recipients=recipient_emails
        )

        return self.send_email(message)


# ============================================================
# 工厂函数
# ============================================================

def create_email_sender(
    smtp_server: str = None,
    smtp_port: int = None,
    smtp_email: str = None,
    smtp_password: str = None
) -> Optional[EmailSender]:
    """
    创建邮件发送器

    Args:
        smtp_server: SMTP服务器
        smtp_port: SMTP端口
        smtp_email: 发件人邮箱
        smtp_password: 邮箱密码

    Returns:
        邮件发送器实例，如果配置不完整返回None
    """
    # 从环境变量获取配置
    smtp_server = smtp_server or os.getenv("SMTP_SERVER", "smtp.qq.com")
    smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
    smtp_email = smtp_email or os.getenv("SMTP_EMAIL")
    smtp_password = smtp_password or os.getenv("SMTP_PASSWORD")

    if not smtp_email or not smtp_password:
        logger.warning("邮件配置不完整，无法创建邮件发送器")
        return None

    config = EmailConfig(
        smtp_server=smtp_server,
        smtp_port=smtp_port,
        smtp_email=smtp_email,
        smtp_password=smtp_password,
        use_tls=True
    )

    return EmailSender(config)


# ============================================================
# 兼容旧接口
# ============================================================

class EmailSenderCompat:
    """兼容旧接口的邮件发送器"""

    def __init__(self, smtp_server, smtp_port, smtp_email, smtp_password):
        config = EmailConfig(
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            smtp_email=smtp_email,
            smtp_password=smtp_password
        )
        self.sender = EmailSender(config)

    def ai_report_to_email(self, ai_report, recipient_emails, report_type=None):
        """兼容旧接口"""
        return self.sender.send_ai_report(
            ai_report=ai_report,
            recipient_emails=recipient_emails,
            report_type=report_type or "健康检查"
        )


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    # 测试邮件发送
    sender = create_email_sender()

    if sender:
        print("邮件发送器创建成功")

        # 测试发送（需要配置真实的邮箱信息）
        # sender.send_ai_report(
        #     ai_report="这是一份测试报告",
        #     recipient_emails=["test@example.com"],
        #     report_type="测试"
        # )
    else:
        print("邮件发送器创建失败，请检查配置")
