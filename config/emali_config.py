# 项目全局SMTP邮件配置（所有模块统一导入，改配置只动这一个文件）
# 文件名说明：原文件名 emali_config.py 是拼写错误，应为 email_config.py，但为避免影响其他导入，保持不变
import os  # 新增：用于读取环境变量

SMTP_CONFIG = {
    "smtp_server": "smtp.qq.com",  # 邮箱SMTP服务器（qq邮箱填smtp.qq.com，企业微信填smtp.qiye.qq.com）
    "smtp_port": 587,  # 端口固定587（所有邮箱通用，不用改）
    "smtp_email": os.getenv("SMTP_EMAIL", "1942601627@qq.com"),  # 优先从环境变量读取
    # 原代码："smtp_password": "dxzlbekmqfqybjfg"  # 安全问题：SMTP授权码硬编码
    # 修复：优先从环境变量读取，环境变量不存在时使用默认值（本地开发用）
    "smtp_password": os.getenv("SMTP_PASSWORD", "dxzlbekmqfqybjfg"),
}  ## 重点：是SMTP授权码，不是邮箱登录密码！建议设置环境变量 SMTP_PASSWORD

# 全局收件人配置（统一管理，不用在邮件类/定时/API里重复写）
RECIPIENT_EMAILS = [
    "2569726146@qq.com",
    "wjz200505154238@petalmail.com",
]  # 领导/自己邮箱1  # 收件人邮箱2，多收件人直接加

# ---------------------- 2. AI周报配置（不用改，默认分析近7天数据） ----------------------
AI_REPORT_DAYS = 7

# ---------------------- 3. 定时任务配置（先不用改，测试完手动发送再调） ----------------------
AUTO_SEND_WEEKDAY = 0  # 每周一发送
AUTO_SEND_HOUR = 9  # 早上9点发送
AUTO_SEND_MINUTE = 0  # 0分发送
