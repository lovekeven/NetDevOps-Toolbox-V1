"""
告警引擎模块
定时检查设备状态，超过阈值时触发告警并发送邮件

功能：
1. 定时检查设备指标（CPU、内存、接口状态等）
2. 与用户配置的阈值比较
3. 超过阈值时触发告警
4. 发送邮件通知
"""

import threading
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from db.database import db_manager
from utils.log_setup import setup_logger

logger = setup_logger("alert_engine", "alert_engine.log")


class AlertEngine:
    """
    告警引擎
    定时检查设备状态，超过阈值时触发告警
    """

    def __init__(self):
        self.is_running = False
        self.check_thread = None
        self.check_interval = 60  # 检查间隔（秒）
        logger.info("告警引擎初始化完成")

    def start(self, interval=60):
        """启动告警引擎"""
        if self.is_running:
            logger.warning("告警引擎已在运行")
            return

        self.is_running = True
        self.check_interval = interval
        self.check_thread = threading.Thread(target=self._check_loop, daemon=True)
        self.check_thread.start()
        logger.info(f"告警引擎启动，检查间隔：{interval}秒")

    def stop(self):
        """停止告警引擎"""
        self.is_running = False
        if self.check_thread:
            self.check_thread.join(timeout=5)
        logger.info("告警引擎已停止")

    def _check_loop(self):
        """检查循环"""
        while self.is_running:
            try:
                self.check_all_rules()
            except Exception as e:
                logger.error(f"告警检查异常：{e}")

            # 等待下次检查
            time.sleep(self.check_interval)

    def check_all_rules(self):
        """检查所有启用的告警规则"""
        rules = db_manager.get_alert_rules(is_enabled=1)
        if not rules:
            return

        logger.info(f"开始检查 {len(rules)} 条告警规则")

        for rule in rules:
            try:
                self._check_single_rule(rule)
            except Exception as e:
                logger.error(f"检查规则 {rule['id']} 失败：{e}")

    def _check_single_rule(self, rule):
        """检查单条告警规则"""
        rule_id = rule['id']
        device_name = rule.get('device_name')
        device_ip = rule.get('device_ip')
        metric_type = rule['metric_type']
        metric_field = rule.get('metric_field')
        operator = rule['threshold_operator']
        threshold = rule['threshold_value']
        severity = rule['severity']

        # 获取设备当前指标值
        current_value = self._get_device_metric(device_ip or device_name, metric_type, metric_field)

        if current_value is None:
            return

        # 比较是否超过阈值
        is_triggered = self._compare_value(current_value, operator, threshold)

        if is_triggered:
            # 触发告警
            message = f"设备 {device_name or device_ip} 的 {metric_type}"
            if metric_field:
                message += f"（{metric_field}）"
            message += f" 当前值 {current_value}，{operator} 阈值 {threshold}"

            # 保存告警历史
            alert_id = db_manager.add_alert_history(
                rule_id=rule_id,
                device_name=device_name or '未知',
                device_ip=device_ip or '',
                metric_type=metric_type,
                metric_value=current_value,
                threshold_value=threshold,
                severity=severity,
                message=message,
            )

            logger.warning(f"告警触发：{message}")

            # 发送邮件
            if rule.get('enable_email_alert') and rule.get('email_recipients'):
                self._send_alert_email(rule, message, current_value)
                db_manager.mark_alert_email_sent(alert_id)

    def _get_device_metric(self, device_id, metric_type, metric_field):
        """
        获取设备指标值
        这里简化处理，实际应该通过SNMP查询
        """
        # 从最新的健康检查记录中获取
        try:
            # 查询最新的健康检查记录
            records = db_manager.get_health_check_records(device_name=device_id, limit=1)
            if not records:
                return None

            record = records[0]

            if metric_type == 'cpu':
                return record.get('cpu_usage')
            elif metric_type == 'memory':
                return record.get('memory_usage')
            elif metric_type == 'interface':
                # 接口状态检查
                interfaces = record.get('interfaces', [])
                if metric_field:
                    for iface in interfaces:
                        if iface.get('name') == metric_field:
                            return 1 if iface.get('status') == 'up' else 0
                return None
            else:
                return None
        except Exception as e:
            logger.error(f"获取设备指标失败：{e}")
            return None

    def _compare_value(self, current_value, operator, threshold):
        """比较当前值和阈值"""
        try:
            current = float(current_value)
            thresh = float(threshold)

            if operator == '>':
                return current > thresh
            elif operator == '<':
                return current < thresh
            elif operator == '>=':
                return current >= thresh
            elif operator == '<=':
                return current <= thresh
            elif operator == '==':
                return current == thresh
            elif operator == '!=':
                return current != thresh
            else:
                return False
        except (ValueError, TypeError):
            return False

    def _send_alert_email(self, rule, message, current_value):
        """发送告警邮件"""
        try:
            # 获取邮件配置
            smtp_server = db_manager.get_setting('smtp_server', 'smtp.qq.com')
            smtp_port = int(db_manager.get_setting('smtp_port', '465'))
            smtp_user = db_manager.get_setting('smtp_user', '')
            smtp_password = db_manager.get_setting('smtp_password', '')

            if not smtp_user or not smtp_password:
                logger.warning("邮件未配置，跳过发送")
                return

            # 获取收件人
            recipients = rule.get('email_recipients', '').split(',')
            recipients = [r.strip() for r in recipients if r.strip()]

            if not recipients:
                logger.warning("没有收件人，跳过发送")
                return

            # 构造邮件
            msg = MIMEMultipart()
            msg['From'] = smtp_user
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = f"[{rule['severity'].upper()}] 网络告警 - {rule['rule_name']}"

            body = f"""
告警详情：
====================
规则名称：{rule['rule_name']}
设备名称：{rule.get('device_name', '所有设备')}
设备IP：{rule.get('device_ip', '所有设备')}
指标类型：{rule['metric_type']}
当前值：{current_value}
阈值：{rule['threshold_operator']} {rule['threshold_value']}
严重级别：{rule['severity']}
触发时间：{time.strftime('%Y-%m-%d %H:%M:%S')}

告警消息：
{message}

====================
请及时处理！
"""
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # 发送邮件
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port)
                server.starttls()

            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipients, msg.as_string())
            server.quit()

            logger.info(f"告警邮件已发送给：{', '.join(recipients)}")

        except Exception as e:
            logger.error(f"发送告警邮件失败：{e}")

    def test_email_config(self, test_recipient):
        """测试邮件配置"""
        try:
            smtp_server = db_manager.get_setting('smtp_server', 'smtp.qq.com')
            smtp_port = int(db_manager.get_setting('smtp_port', '465'))
            smtp_user = db_manager.get_setting('smtp_user', '')
            smtp_password = db_manager.get_setting('smtp_password', '')

            if not smtp_user or not smtp_password:
                return False, "邮件未配置"

            msg = MIMEMultipart()
            msg['From'] = smtp_user
            msg['To'] = test_recipient
            msg['Subject'] = "测试邮件 - NetDevOps工具箱"
            body = "这是一封测试邮件，邮件配置正常！"
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            else:
                server = smtplib.SMTP(smtp_server, smtp_port)
                server.starttls()

            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [test_recipient], msg.as_string())
            server.quit()

            return True, "发送成功"
        except Exception as e:
            return False, str(e)


# 全局告警引擎实例
alert_engine = AlertEngine()
