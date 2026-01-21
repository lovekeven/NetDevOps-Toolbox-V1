import psutil
import os
import sys
from datetime import datetime
from utils.log_setup import setup_logger
from db.database import db_manager
import requests
from core.nornir.nornir_tasks import run_concurrent_health_check

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
logger = setup_logger("montioring", "montioring.log")


class SystemMonitor:
    @staticmethod
    def collect_system_metrics():
        """收集系统级别的指标"""
        try:
            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            # 内存使用率
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            # 磁盘使用率
            disk = psutil.disk_usage(".")  # 当前文件所在的磁盘
            disk_percent = disk.percent
            # 网络I/O
            net_io = psutil.net_io_counters()
            metrics = {
                "timestamp": datetime.now().isoformat(),
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "memory_used_gb": round((memory.used / (1024**3)), 2),
                "memory_total_gb": round((memory.total / (1024**3)), 2),
                "disk_percent": disk_percent,
                "disk_used_gb": round((disk.used / (1024**3)), 2),
                "disk_total_gb": round((disk.total / (1024**3)), 2),
                "network_bytes_sent": net_io.bytes_sent,
                "network_bytes_recv": net_io.bytes_recv,
                "network_packets_sent": net_io.packets_sent,
                "network_packets_recv": net_io.packets_recv,
            }
            logger.info(
                f"收集系统级别指标成功！CPU使用率{cpu_percent}，内存使用率{memory_percent},磁盘使用率{disk_percent}"
            )
            return metrics
        except Exception as e:
            error_msg = str(e)
            logger.error(f"收集系统级别指标异常！{error_msg[:100]}")
            raise

    @staticmethod
    def check_service_status():
        """检查关键服务的健康状态"""
        services_status = {
            "web_dashboard": "unknown",
            "database": "unknown",
            "nornir_engine": "unknown",
        }
        try:
            # 检查数据库连接
            try:
                recoard = db_manager.get_recent_backups(limit=1)  # 取所有设备的备份历史记录的第一条
                logger.info("数据库连接正常！")
                services_status["database"] = "healthy"
            except Exception as e:
                error_msg = str(e)
                services_status["database"] = f"unhealthy:{error_msg[:100]}"
                logger.error(f"数据库连接服务失败！{error_msg[:100]}")
            # 检查Web仪表盘
            try:
                Web_dashboard_URL = "http://127.0.0.1:8080"
                response = requests.get(Web_dashboard_URL, timeout=5)  # 五秒连不上就不连了
                response.raise_for_status()  # 只管「HTTP 状态码异常」
                logger.info(f"Web仪表盘网络地址访问正常！，状态码:{response.status_code}")
                services_status["web_dashboard"] = "healthy"
            except requests.exceptions.HTTPError as e:
                error_msg = str(e)
                services_status["web_dashboard"] = f"unhealthy: HTTP错误 {e}"
                logger.error(f"Web仪表盘网络地址访问失败！{error_msg[:100]}")
            except requests.exceptions.ConnectionError:
                services_status["web_dashboard"] = "unhealthy: 无法连接"
            except requests.exceptions.Timeout:
                services_status["web_dashboard"] = "unhealthy: 超时"
            except Exception as e:
                services_status["web_dashboard"] = f"unhealthy: 未知错误 {str(e)[:50]}"
                logger.error(f"Web仪表盘网络地址访问失败！{error_msg[:100]}")
            # 检查Nornir框架
            try:
                result = run_concurrent_health_check(hosts="SW1")
                logger.info("Nornir框架运行正常！")
                services_status["nornir_engine"] = "healthy"
            except Exception as e:
                logger.error(f"Nornir框架运行异常！{str(e)[:100]}")
                services_status["nornir_engine"] = f"unhealthy: {str(e)[:100]}"
            return services_status
        except Exception as e:
            logger.error(f"检查关键服务的健康状态出现严重错误{str(e)[:100]}")
            raise

    @staticmethod
    def log_metrics_to_db():
        metrics = SystemMonitor.collect_system_metrics()
        if metrics:
            try:
                db_manager.log_system_metrics(metrics_dict=metrics)
                logger.info(f"系统指标已记录到数据库: {metrics['timestamp']}")
            except Exception as e:
                logger.error(f"记录系统指标到数据库失败: {e}")


# 把 psutil 采集的本地指标，翻译成 Prometheus 能看懂的 “语言”
def get_prometheus_metrics():
    """生成Prometheus格式的指标（用于/metrics端点）"""
    metrics = SystemMonitor.collect_system_metrics()
    if not metrics:
        return "# 无法收集指标\n"
    prometheus_output = []
    prometheus_output.append("# HELP system_cpu_percent CPU使用百分比")
    prometheus_output.append("# TYPE system_cpu_percent gauge")
    prometheus_output.append(f"system_cpu_percent {metrics['cpu_percent']}")

    prometheus_output.append("# HELP system_memory_percent 内存使用百分比")
    prometheus_output.append("# TYPE system_memory_percent gauge")
    prometheus_output.append(f"system_memory_percent {metrics['memory_percent']}")

    prometheus_output.append("# HELP system_disk_percent 磁盘使用百分比")
    prometheus_output.append("# TYPE system_disk_percent gauge")
    prometheus_output.append(f"system_disk_percent {metrics['disk_percent']}")

    return "\n".join(prometheus_output)
