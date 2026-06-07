from concurrent.futures import thread
from datetime import datetime
import sys
import os

import requests

print(f"当前Python路径：{sys.executable}")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from db.database import db_manager

# 导入下载模块
from flask import jsonify, Flask, render_template, request, send_from_directory, send_file
from flask_socketio import SocketIO, emit

# 1.jsonify就是为了返回JSON格式的数据
from core.health_check.health_checker import check_single_device
from core.backup.backup_handler import backup_single_device
import yaml

# 引入AI这个全局实例
from core.AI.report_generator import deepseek_assistant
from core.nornir.nornir_tasks import run_concurrent_health_check
from utils.log_setup import setup_logger
import logging  # 这个可以不用写
from core.monitoring.monitoring import SystemMonitor, get_prometheus_metrics

# 引入模拟云服务平台
from core.cloud.concept_simulator import CloudNetworkSimulator

cloud_simulator = CloudNetworkSimulator()

# 引入真实阿里云客户（可选）
try:
    from core.cloud.real_providers.ali_client import AliyunCloudClient
    aliyun_client_available = True
except ImportError:
    aliyun_client_available = False
    AliyunCloudClient = None

# 引入混合资源管理器(全局实例)
from core.hybrid_manager.hybrid_manager import HybridResourceManager

hybrid_manager = HybridResourceManager(cloud_mode="simulated")
# 引入全局的物理设备档案卡
from utils.models import get_global_physical_cards

# 引入邮件发送器（类）
from utils.email_sender import EmailSender

# 引入发送邮箱的配置文件
from config import emali_config

# 引入定时发送任务的核心类
from apscheduler.schedulers.background import BackgroundScheduler

# 引入netmiko测试连接
from netmiko import ConnectHandler

# 引入多线程模块
import threading

# 引入拓扑模块
import asyncio
from core.topology.snmp_collector import SNMPCollector, PYSNMP_AVAILABLE
from core.topology.topology_builder import TopologyBuilder
from core.topology.sdn_collector import SDNCollector
from core.topology.network_tools import NetworkTools

# 引入终端模块
from core.terminal.web_terminal import terminal_manager

logger = setup_logger("web_dashboard", "web_dashboard.log")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'netdevops-secret-key'

# 初始化 WebSocket
socketio = SocketIO(app, cors_allowed_origins="*")

# 设备清单路径
CONFIG_PATH = os.path.join(ROOT_DIR, "config", "nornir_inventory.yaml")


# 第二步：改造解析逻辑，适配你的扁平化Nornir清单（关键改2）
def get_devices(filename=CONFIG_PATH):
    device_list = []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            # 你的Nornir清单顶层就是设备名，无外层"devices"键，直接遍历data.items()（核心改）
            for device_name, device_info in data.items():
                # 逐层提取字段，加容错get，避免字段不存在时报错（关键）
                netmiko_extras = device_info.get("connection_options", {}).get("netmiko", {}).get("extras", {})
                data = device_info.get("data", {})
                device = {
                    "device_name": device_name,  # 保持原有键，兼容后续逻辑
                    "device_type": netmiko_extras.get("device_type", "未知"),  # 从netmiko配置取设备类型
                    "host": device_info.get("hostname", ""),  # 顶层取IP/主机名
                    "username": device_info.get("username", ""),  # 顶层取用户名
                    "password": device_info.get("password", ""),  # 顶层取密码
                    "port": netmiko_extras.get("port", 22),  # 从netmiko配置取端口，默认22
                    "vendor": data.get("vendor", "华三H3C"),
                }
                # 过滤空设备（防止清单有无效配置）
                if device["host"] and device["username"] and device["password"]:
                    device_list.append(device)
        logger.info(f"从Nornir清单读取设备成功，共{len(device_list)}台")
        return device_list
    except Exception as e:
        logger.error(f"错误：未成功读取Nornir设备文件 - {e}")
        return device_list


@app.route("/")
def index():
    devices = get_devices()

    def check_device_status(dev):
        try:
            # 测试连接
            dev_copy = dev.copy()
            if "device_name" in dev_copy:
                del dev_copy["device_name"]
                del dev_copy["vendor"]
            connection = ConnectHandler(**dev_copy, timeout=2)
            # Netmiko 默认超时约 10 秒，若有 1 台设备离线，页面会卡在这台设备的连接上 10 秒，设备多的话加载会极慢，加 2
            #  秒超时后，单台设备连不上会立刻判离线，页面加载速度会大幅提升。
            connection.disconnect()
            dev["status"] = "在线"
            logger.info(f"连接设备 {dev['device_name']} 成功")
        except Exception as e:
            logger.error(f"连接设备 {dev['device_name']} 失败: {e}")
            dev["status"] = "离线"

    threads = []
    for dev in devices:
        thread = threading.Thread(target=check_device_status, args=(dev,))
        # 参数那里只能以元组的形式
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()

    return render_template("index.html", devices=devices)


# 第一个API接口：对设备的健康检查
@app.route("/api/health/<device_name>")
def device_health(device_name):
    devices = get_devices()
    target_device = next((d for d in devices if d["device_name"] == device_name), None)
    # 1.里面的生成器表达式是筛选符合标准的设备，在这里可能是0个或者1个，结果就是只包含符合条件的设备
    # 2.next()是 Python 的内置函数，核心作用是：从「可迭代对象」（比如这里的生成器表达式）中，取出「第一个」元素。
    # 关键是：next()只取「第一个」元素，取到后就停止，不会继续遍历后面的设备（和你for循环里加break的效果一致，效率很高）
    # 3.：next(..., None) —— 优雅处理「没找到设备」的情况（第二个参数）
    # next()函数可以传两个参数：
    # 第一个参数：要遍历的可迭代对象（生成器表达式）；
    # 第二个参数：「当可迭代对象中没有元素时（也就是没找到符合条件的设备），返回的默认值」
    # 4.matched_devices = [d for d in devices if d['device_name'] == hostname]如果用这个列表推导式的话，
    # 会一次性遍历完整个devices列表，生成一个完整的符合条件的  列表，又得遍历太麻烦
    if not target_device:
        return jsonify({"error": "设备未找到"}), 404
        # 1.jsonify函数里面的参数最常见的就是键值对
        # 2.jsonify函数把参数转换成了符合HTTP协议规范的JOSN格式响应，就是转换成JSON格式的字符串，这个函数在打包就是符合http规范
        # 4.return把这个 “打包好的 JSON 响应” 返回给客户端
    try:
        target_device_copy = target_device.copy()
        if "device_name" in target_device_copy:
            del target_device_copy["device_name"]
            del target_device_copy["vendor"]
        result = check_single_device(target_device_copy)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"检查时出现错误！{e}"}), 500


# 第二个API接口：对设备的备份
@app.route("/api/backup/<device_name>")
# Flask 拿到路由提取的键值对（如device_name="SW1"）后，确实会去查看对应视图函数的参数列表，这是传参的前提；
def device_backup(device_name):
    # 1.传参的核心目的：通过「唯一标识」准确提取设备：无论是device_name还是IP地址，本质都是设备的「唯一标识」
    # （一个设备对应一个唯一名称 / 一个唯一 IP），传参的核心就是用这个唯一标识，从设备列表中精准找到目标设备，这也是你说的 “90% 的核心目的”
    devices = get_devices()
    target_device = next((d for d in devices if d["device_name"] == device_name), None)
    if not target_device:
        return (
            jsonify(
                {
                    "device_name": device_name,
                    "status": "失败",
                    "message": "设备未找到",
                    "backup_path": "N/A",
                }
            ),
            404,
        )
    try:
        target_device_copy = target_device.copy()
        if "device_name" in target_device_copy:
            del target_device_copy["device_name"]
            del target_device_copy["vendor"]
        # 1.下面是你备份的函数吧，你调用的时候，他会先建立连接这个时候**device_info解包的时候，连接库不认识device_name这个参数
        start_time = datetime.now()
        # 接收备份函数返回的实际文件路径
        backup_path = backup_single_device(target_device_copy)
        end_time = datetime.now()
        
        # 如果返回的不是字符串（备份失败），抛出异常
        if not isinstance(backup_path, str):
            raise Exception("备份函数未返回有效路径")
        # 向数据库表中插入数据
        db_manager.log_backup(
            hostname=device_name,
            backup_path=backup_path,
            status="success",
            start_time=start_time,
            end_time=end_time,
            backup_size=1024,
        )
        return jsonify(
            {
                "device_name": device_name,
                "host": target_device["host"],
                "status": "成功",
                "message": "设备配置备份成功",
                "backup_path": backup_path,
                "record_id": "已记录到数据库",
            }
        )
    except Exception as e:
        error_msg = str(e)
        # 传给数据库
        db_manager.log_backup(
            hostname=device_name,
            backup_path="N/A",
            status="failed",
            error_message=error_msg[:100],
            start_time=datetime.now(),
        )
        return_message = {
            "device_name": device_name,
            "host": target_device["host"],
            "status": "失败",
            "message": "设备配置备份时出现错误",
            "backup_path": "N/A",
            "error_msg": error_msg[:100],
        }
        return jsonify(return_message), 500


# 批量备份所有设备
@app.route("/api/backup/all", methods=["POST"])
def batch_backup_all():
    """批量备份所有设备配置"""
    devices = get_devices()
    if not devices:
        return jsonify({"code": 1, "msg": "没有设备", "data": None}), 400

    success_count = 0
    failed_count = 0
    results = []

    for dev in devices:
        device_name = dev["device_name"]
        try:
            dev_copy = dev.copy()
            if "device_name" in dev_copy:
                del dev_copy["device_name"]
                del dev_copy["vendor"]

            start_time = datetime.now()
            backup_path = backup_single_device(dev_copy)
            end_time = datetime.now()

            if isinstance(backup_path, str):
                db_manager.log_backup(
                    hostname=device_name,
                    backup_path=backup_path,
                    status="success",
                    start_time=start_time,
                    end_time=end_time,
                )
                success_count += 1
                results.append({"device": device_name, "status": "成功"})
            else:
                raise Exception("备份失败")
        except Exception as e:
            db_manager.log_backup(
                hostname=device_name,
                backup_path="N/A",
                status="failed",
                error_message=str(e)[:100],
                start_time=datetime.now(),
            )
            failed_count += 1
            results.append({"device": device_name, "status": "失败", "error": str(e)[:50]})

    return jsonify({
        "code": 0,
        "msg": f"批量备份完成: {success_count} 成功, {failed_count} 失败",
        "data": {
            "success": success_count,
            "failed": failed_count,
            "results": results
        }
    })


def check_internal_service_health():
    return "healthy", "API服务运行正常"


# 第三个API接口：检查API服务运行状态
@app.route("/api/service_status")
def api_service_status():
    try:
        status, message = check_internal_service_health()
        return (
            jsonify(
                {
                    "status": status,
                    "message": message,
                }
            ),
            200,
        )
    except Exception as e:
        error = str(e)
        return jsonify({"status": "API基本服务连接失败", "message": "API服务运行异常", "error": error[:100]}), 500


# 第四个API接口查看设备备份历史
@app.route("/api/backup/history/")
@app.route("/api/backup/history/<device_name>")
def backup_history(device_name=None):
    # 点击查询所有历史记录的时候，URL让他拼接成days = 0,limit = 0,
    try:
        days = request.args.get("days", default=7, type=int)
        limit = request.args.get("limit", default=20, type=int)
        # 原代码：recoard = ...  # 拼写错误：recoard 应为 record
        record = db_manager.get_recent_backups(hostname=device_name, limit=limit, days=days)
        return jsonify({"status": "success", "history_record": len(record), "history": record})
    except Exception as e:
        error_msg = str(e)
        return (
            jsonify(
                {
                    "status": "failed",
                    "error_msg": error_msg[:100],
                    "history_record": 0,
                }
            ),
            500,
        )


# 第五个API接口调用Deepseek大模型
ALL_BACKUP_REPORT_CACHE = {}


@app.route("/api/backup_record/ai/")
def ai_report_about_backup():
    if deepseek_assistant is None:
        logger.error("AI报告接口调用失败：deepseek_assistant 未初始化（API Key错误）")
        return (
            jsonify({"code": 500, "message": "Deepseek调用失败,请查看API key", "data": None, "deepseek_status": "N/A"}),
            500,
        )
    try:
        days = request.args.get("days", default=7, type=int)
        report = deepseek_assistant.get_deepseek_content(days=days)
        logger.info("AI报告接口调用成功，报告生成完成")
        cache_key = f"days_{days}"
        ALL_BACKUP_REPORT_CACHE[cache_key] = {
            "report_content": report,
            "create_time": datetime.now().timestamp(),
        }
        # 3. 成功返回（统一格式）
        return (
            jsonify(
                {
                    "code": 200,
                    "message": "报告生成成功",
                    "data": report,
                    "deepseek_status": "normal",
                    "report_time": datetime.now().isoformat(),
                }
            ),
            200,
        )
    except Exception as e:
        error_msg = str(e)[:100]
        logger.error(f"AI报告接口调用失败：{error_msg}")
        # 4. 失败返回（统一格式）
        return (
            jsonify(
                {"code": 500, "message": "Deepseek调用失败", "data": None, "error_detail": "服务端处理异常，请稍后重试"}
            ),
            500,
        )


@app.route("/api/backup_record/ai/email/send", methods=["POST"])
def send_backup_email():
    if deepseek_assistant is None:
        logger.error("AI报告接口调用失败：deepseek_assistant 未初始化（API Key错误）")
        return (
            jsonify({"code": 500, "message": "Deepseek调用失败,请查看API key", "data": None, "deepseek_status": "N/A"}),
            500,
        )
    try:
        try:
            datas = request.get_json(force=True, silent=False)
            logger.info("成功解析请求体的内容！")
        except Exception as e:
            logger.error(f"解析请求体失败 {e}")
            return (
                jsonify({"code": 400, "message": "请求参数错误，请传入合法的JSON数据", "send_status": "fail"}),
                400,
            )
        days = datas.get("days", request.args.get("days", default=7, type=int))
        cache_key = f"days_{days}"
        # 判断缓存字典里面是否有这个参数
        if cache_key not in ALL_BACKUP_REPORT_CACHE:
            logger.error(f"发送邮件失败！请先生成近{days}天的AI报告！")
            return (
                jsonify(
                    {"code": 404, "message": f"未找到近{days}天的AI报告，请先生成报告再发送", "send_status": "fail"}
                ),
                404,
            )
        # 判断是否过期
        now_timestamp = datetime.now().timestamp()
        if now_timestamp - ALL_BACKUP_REPORT_CACHE[cache_key]["create_time"] > CACHE_EXPIRE_SECONDS:
            del ALL_BACKUP_REPORT_CACHE[cache_key]  # 删除缓存内容
            logger.error(f"发送邮件失败!,已经超过30分钟!请重新获取AI报告内容")
            return (
                jsonify(
                    {"code": 409, "message": f"AI报告已过期（超过30分钟），请重新生成后再发送", "send_status": "fail"}
                ),
                409,  # 缓存过期应该用409 冲突
            )
        # 满足以上两个条件可以发送邮箱了
        data = ALL_BACKUP_REPORT_CACHE[cache_key]["report_content"]
        email_sendor = EmailSender(**emali_config.SMTP_CONFIG)
        email_sendor.ai_report_to_email(
            ai_report=data,
            recipient_emails=emali_config.RECIPIENT_EMAILS,
            report_type=f"所有设备近{days}的备份情况AI报告",
        )
        logger.info(f"全网设备近{days}天备份AI报告发送邮箱成功，收件人：{emali_config.RECIPIENT_EMAILS}")
        return (
            jsonify(
                {
                    "code": 200,
                    "message": "全网备份AI报告已成功发送至指定邮箱",
                    "send_status": "success",
                    "report_days": days,
                    "recipient_count": len(emali_config.RECIPIENT_EMAILS),
                }
            ),
            200,
        )
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error(f"全网备份AI报告发送邮箱失败：{error_msg}")
        return (
            jsonify({"code": 500, "message": "AI报告发送邮箱失败", "send_status": "fail", "error_detail": error_msg}),
            500,
        )


# 第六个API接口使用Nornir并发检查设备
@app.route("/api/health/nornir-check")
def nornir_check_health():
    try:
        device_list = request.args.get("devices", "")
        # 1.request.args.get('device') 只能获取「单个device参数对应的单个值」（比如?device=SW1，只能拿到"SW1"），无法直接获取
        # 多个设备名；
        # 2.request.args.get("devices", "") 确实只获取「单个值」
        # 3.比如访问?devices = SW1,SW2,SW3,那么device_list里面就是一个普通的字符串
        # 4.get 方法的两个参数—— 第一个参数是 “要找的参数名”，第二个参数是 “默认值”
        hosts = device_list.split(",") if device_list else None
        # 1.split函数返回的是列表
        result = run_concurrent_health_check(hosts=hosts)
        return jsonify(result)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"并发检查失败{error_msg[:100]}")
        return jsonify({"error": str(e)}), 500


# 第七个API接口：Prometheus指标端点
@app.route("/metrics")
def metrics_endpoint():
    try:
        prometheus_output = get_prometheus_metrics()
        logger.info("获取Prometheus格式的指标成功！")
        return prometheus_output, 200, {"Content-Type": "text/plain"}
        # 返回的这种数据类型是那个程序认识，前端也可以解析
    except Exception as e:
        error_msg = str(e)
        logger.error(f"获取Prometheus格式的指标失败！{error_msg[:100]}")
        return (
            jsonify(
                {
                    "status": "failed",
                    "message": "N/A",
                    "error": error_msg[:100],
                }
            ),
            500,
        )


# 第八个API接口：检查关键服务健康状态
@app.route("/api/system/healthy")
def check_system_health():
    try:
        system_metrics = None
        system_metrics_error = None  # 就是一个空值 if not sys.....会是True
        try:
            system_metrics = SystemMonitor.collect_system_metrics()
        except Exception as e:
            error = str(e)
            system_metrics_error = error[:100]
        service_status = SystemMonitor.check_service_status()
        all_health = all(status == "healthy" or "healthy" in str(status) for status in service_status.values())
        return jsonify(
            {
                "healthy": "healthy" if all_health else "degraded",
                "timestamp": datetime.now().isoformat(),
                "status": "检查成功",
                "service_status": service_status,
                "system_metrics": system_metrics if system_metrics_error is None else system_metrics_error,
            }
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"检查服务健康状态出现严重错误{error_msg[:100]}")
        return (
            jsonify(
                {
                    "healthy": "unhealthy",
                    "timestamp": datetime.now().isoformat(),
                    "status": "检查失败",
                    "service_status": "N/A",
                    "system_metrics": "N/A",
                }
            ),
            500,
        )


# 第九个API接口获取云端模拟资源，可切换模拟/真实模式
@app.route("/api/cloud/resources")
def get_cloud_resources():
    """获取云资源（可切换模拟/真实模式）"""

    mode = request.args.get("simulated", "real")
    if mode == "real":
        ALIYUN_AK = os.getenv("ALIYUN_AK")
        ALIYUN_SK = os.getenv("ALIYUN_SK")
        ALIYUN_REGION_ID = os.getenv("ALIYUN_REGION_ID", "cn-hangzhou")
        if not ALIYUN_AK or not ALIYUN_SK:
            logger.error("请在环境变量清单中设置对应的阿里云密钥")
            return (
                jsonify({"error": "未配置阿里云凭证", "message": "请设置ALIYUN_AK和ALIYUN_SK环境变量"}),
                400,
            )  # 用户未传必要信息
        resource_type = request.args.get("type", "all")
        try:
            client = AliyunCloudClient(ALIYUN_AK, ALIYUN_SK, ALIYUN_REGION_ID)
            logger.info("初始化阿里云客户端成功！")
            if resource_type == "all":
                try:
                    all_resourse = client.get_all_resources()
                    logger.info("获取全部真实云资源成功！")
                    return jsonify([all_re.to_dict() for all_re in all_resourse])
                except Exception as e:
                    error_msg = str(e)  # 修复：原代码使用了未定义的 error_msg，改为从 e 获取
                    logger.error(f"获取全部真实网络资源失败{error_msg}")
                    return jsonify({"error": f"获取全部真实网络资源失败{error_msg[:200]}"}), 500
            else:
                if resource_type == "vpc":
                    try:
                        vpcs = client.get_vpcs()
                        logger.info("获取VPC列表成功")
                        return jsonify([vpc.to_dict() for vpc in vpcs])
                    except Exception as e:
                        error_msg = str(e)
                        return (
                            jsonify({"error": f"获取VPC列表失败{error_msg[:200]}", "message": "请查看相关配置"}),
                            500,
                        )
                else:
                    try:
                        security_groups = client.get_all_security_groups()
                        logger.info("获取全部真实安全组成功！")
                        return jsonify([sec.to_dict() for sec in security_groups])
                    except Exception as e:
                        error_msg = str(e)
                        return (
                            jsonify({"error": f"获取真实安全组失败{error_msg[:200]}", "message": "请查看相关配置"}),
                            500,
                        )

        except Exception as e:
            error_msg = str(e)
            return (
                jsonify(
                    {"error": "初始化阿里云客户端失败！", "message": "请查看你ALIYUN_A和ALIYUN_SK环境变量是否配置正确"}
                ),
                401,
            )  # 凭证无效，认证失败

    else:
        try:
            resource_type = request.args.get("type", "all")

            if resource_type.lower() == "vpc":
                cloud_resources = cloud_simulator.get_resource_by_type(resource_type=resource_type)
                if not cloud_resources:
                    return jsonify({"status": "failed", "message": "未寻找到vpc模拟资源", "cloud_resources": []}), 404
                # 返回类型是列表（元素是字典）
                return jsonify(
                    {
                        "status": "success",
                        "message": "云网络资源（模拟数据）",
                        "data": cloud_resources,
                        "count": len(cloud_resources),
                        "note": "此为概念演示，展示平台可扩展至管理云网络资源",
                    }
                )
            elif resource_type.lower() == "securitygroup":
                cloud_resources = cloud_simulator.get_resource_by_type(resource_type=resource_type)
                if not cloud_resources:
                    return (
                        jsonify({"status": "failed", "message": "未寻找到安全组模拟资源", "cloud_resources": []}),
                        404,
                    )
                # 返回类型是列表（元素是字典）
                return jsonify(
                    {
                        "status": "success",
                        "message": "云网络资源（模拟数据）",
                        "data": cloud_resources,
                        "count": len(cloud_resources),
                        "note": "此为概念演示，展示平台可扩展至管理云网络资源",
                    }
                )
            elif resource_type == "all":
                cloud_resources = cloud_simulator.get_all_resources()
                # 返回类型是列表（元素是字典
                if not cloud_resources:
                    return jsonify({"status": "failed", "message": "未寻找到vpc模拟资源", "cloud_resources": []}), 404
                return jsonify(
                    {
                        "status": "success",
                        "message": "云网络资源（模拟数据）",
                        "data": cloud_resources,
                        "count": len(cloud_resources),
                        "note": "此为概念演示，展示平台可扩展至管理云网络资源",
                    }
                )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"获取模拟器资源出现错误{error_msg[:200]}")
            return jsonify({"status": "failed", "message": error_msg[:200], "cloud_resources": "N/A"}), 500
        # 第九个API接口写的时候可以更简便，一个if eles 就可以搞定，因为不是all就是其他类型


# 第十个API接口模拟创建VPC
# 写的methods=['POST']，就是告诉服务器：“这个接口只听 POST 这句悄悄话，其他话（比如 GET）一概不理”。
@app.route("/api/cloud/simulate/create_vpc", methods=["POST"])
# 普通用户在地址栏输入这个 URL，按下回车：浏览器发 GET 请求 → 后端限定了只接受 POST → 返回 405 错误（Method Not Allowed）；
def create_vpc():
    try:
        data = request.get_json()
        # Flask这个底层帮我干好了,他帮我干好了现在data已经是一个字典了
        if not data or "name" not in data:
            # 他这里为啥不判断其他参数情况，因为下面给他设默认值了
            return (
                jsonify({"status": "failed", "message": "缺少name参数"}),
                400,
            )  # HTTP 400（Bad Request）的官方定义：客户端（前端
        # / 浏览器）发送的请求有「语法错误」或「参数不合法」，服务器无法理解 / 处理这个请求，返回 400。
        result = cloud_simulator.simulate_creating_vpc(
            name=data["name"], cidr=data.get("cidr", "10.0.0.0/16"), region=data.get("region", "cn-east-1")
        )
        return jsonify(result)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"模拟创建VPC失败 {error_msg[:100]}")
        return jsonify({"status": "failed", "message": f"模拟创建VPC失败{error_msg[:100]}"}), 500


# 第十一个API接口云网络概念演示页面
@app.route("/cloud")
def cloud_demo():
    return render_template("cloud_demo.html")  # 这里没有填充物，是一个静态页面，也可以实现交互


# 第十二个API接口从真实阿里云获取VPC列表和安全组


# @app.route("/api/cloud/real/vpcs", methods=["GET"])
# def get_real_vpc():
#     ALIYUN_AK = os.getenv("ALIYUN_AK")
#     ALIYUN_SK = os.getenv("ALIYUN_SK")
#     ALIYUN_REGION_ID = os.getenv("ALIYUN_REGION_ID", "cn-hangzhou")
#     if not ALIYUN_AK and not ALIYUN_SK:
#         logger.error("请在环境变量清单中设置对应的阿里云密钥")
#         return (
#             jsonify({"error": "未配置阿里云凭证", "message": "请设置ALIYUN_A和ALIYUN_SK环境变量"}),
#             400,
#         )  # 用户未传必要信息
#     try:
#         client = AliyunCloudClient(ALIYUN_AK, ALIYUN_SK, ALIYUN_REGION_ID)
#         logger.info("初始化阿里云客户端成功！")
#         try:
#             vpcs = client.get_vpcs()
#             logger.info("获取VPC列表成功")
#             return jsonify([vpc.to_dict() for vpc in vpcs])
#         except Exception as e:
#             error_msg = str(e)
#             return (
#                 jsonify(
#                     {
#                         "error": f"获取VPC列表失败{error_msg[:200]}",
#                     }
#                 ),
#                 500,
#             )
#     except Exception as e:
#         error_msg = str(e)
#         return (
#             jsonify(
#                 {"error": "初始化阿里云客户端失败！", "message": "请查看你ALIYUN_AK和ALIYUN_SK环境变量是否配置正确"}
#             ),
#             401,
#         )  # 凭证无效，认证失败


# 第十三个API接口：获取混合资源（物理设备+云资源）
@app.route("/api/hybrid/resources", methods=["GET"])
def get_hybrid_resources():
    try:
        # 按ID获取
        resource_id = request.args.get("id")
        if resource_id:
            logger.info(f"ID查询模式:正在查询{resource_id}.......")
            resource = hybrid_manager.get_resource_by_id(resource_id=resource_id)
            if not resource:
                logger.error(f"ID查询模式:未找到ID为 {resource_id} 的资源")
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": f"未找到ID为 {resource_id} 的资源",
                            "timestamp": datetime.now().isoformat(),
                        }
                    ),
                    404,
                )

            resources_dict = resource.to_dict()
            logger.info(f"ID查询模式:查询{resource_id}成功！")
            count = 1
        else:
            # 按类型获取
            resource_type = request.args.get("type", "all")
            logger.info(f"按类型获取资源: type={resource_type}")
            if resource_type == "all":
                resources = hybrid_manager.get_all_resources()
                logger.info(f"获取所有资源成功, 数量: {len(resources)}")
            else:
                resources = hybrid_manager.get_resource_by_type(resource_type)
                logger.info(f"获取类型为 {resource_type} 的资源成功, 数量: {len(resources)}")
            resources_dict = [r.to_dict() for r in resources]
            count = len(resources_dict)
            logger.info(f"资源总数: {count}")
        return (
            jsonify(
                {
                    "status": "success",
                    "message": "混合云网络资源",
                    "mode": hybrid_manager.cloud_model,
                    "data": resources_dict,  # 一个是字典多个是列表，如果是一个的话len函数是计算的一共有几个键值对
                    "count": count,
                    "timestamp": datetime.now().isoformat(),
                }
            ),
            200,
        )
    except Exception as e:
        logger.error(f"获取混合资源失败: {e}")
        return jsonify({"status": "error", "message": f"获取混合资源失败: {str(e)[:200]}"}), 500


# 第十四个API接口：获取混合资源健康状态
@app.route("/api/hybrid/health", methods=["GET"])
def get_hybrid_health():
    try:
        summary = hybrid_manager.get_health_summary()
        logger.info("获取混合资源健康状态成功！")
        return jsonify({"status": "success", "data": summary})
    except Exception as e:
        logger.error(f"获取健康状态失败: {e}")
        return jsonify({"status": "error", "message": f"获取健康状态失败: {str(e)[:200]}"}), 500


# 第十五个API接口：设置云资源模式
@app.route("/api/hybrid/mode", methods=["POST"])
def set_cloud_mode():
    try:
        data = request.get_json(force=True, silent=False)
        mode = data.get("mode", "simulated")
        if mode not in ["simulated", "real"]:
            return jsonify({"status": "error", "message": "模式必须是 'simulated' 或 'real'"}), 400
        global hybrid_manager
        # 1.def __init__(self, cloud_mode="simulated"):也就是说只有初始化的时候才会执行这个，如果只改参数的话是不执行这个的
        # 资源还是原来的旧资源，所以这里要重新初始化，新实例之前还是用旧的
        hybrid_manager = HybridResourceManager(cloud_mode=mode)
        logger.info(f"正在进入{mode}模式.......")
        logger.info(f"模式切换成功,当前模式{mode}")
        return (
            jsonify(
                {
                    "status": "success",
                    "message": f"已切换到 {mode} 模式",
                    "resource_count": len(hybrid_manager.all_resources),
                }
            ),
            200,
        )
    except Exception as e:
        logger.error(f"模式切换失败{e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"模式切换失败{e}",
                    "resource_count": "N/A",
                }
            ),
            500,
        )


# 第十六个API接口：混合仪表盘页面
@app.route("/hybrid")
def hybrid_dashboard():
    """混合仪表盘页面"""
    return render_template("hybrid_dashboard.html")


# ============================================================
# 对接真实阿里云增强功能（质变级优化 #4）
# ============================================================

@app.route("/api/v1/aliyun/ecs", methods=["GET"])
def get_aliyun_ecs_instances():
    """获取阿里云 ECS 实例列表"""
    try:
        ALIYUN_AK = os.getenv("ALIYUN_AK")
        ALIYUN_SK = os.getenv("ALIYUN_SK")
        ALIYUN_REGION_ID = os.getenv("ALIYUN_REGION_ID", "cn-hangzhou")

        if not ALIYUN_AK or not ALIYUN_SK:
            return jsonify({
                "code": 1,
                "msg": "未配置阿里云凭证，请设置 ALIYUN_AK 和 ALIYUN_SK 环境变量",
                "data": None
            }), 400

        client = AliyunCloudClient(ALIYUN_AK, ALIYUN_SK, ALIYUN_REGION_ID)
        instances = client.get_all_instances()

        return jsonify({
            "code": 0,
            "msg": f"获取成功，共 {len(instances)} 个 ECS 实例",
            "data": {
                "region": ALIYUN_REGION_ID,
                "instances": instances,
                "count": len(instances)
            }
        })
    except Exception as e:
        logger.error(f"获取阿里云 ECS 实例失败：{str(e)}")
        return jsonify({"code": 1, "msg": f"获取失败：{str(e)}", "data": None}), 500


@app.route("/api/v1/aliyun/vpc", methods=["GET"])
def get_aliyun_vpc_list():
    """获取阿里云 VPC 列表"""
    try:
        ALIYUN_AK = os.getenv("ALIYUN_AK")
        ALIYUN_SK = os.getenv("ALIYUN_SK")
        ALIYUN_REGION_ID = os.getenv("ALIYUN_REGION_ID", "cn-hangzhou")

        if not ALIYUN_AK or not ALIYUN_SK:
            return jsonify({
                "code": 1,
                "msg": "未配置阿里云凭证",
                "data": None
            }), 400

        client = AliyunCloudClient(ALIYUN_AK, ALIYUN_SK, ALIYUN_REGION_ID)
        vpcs = client.get_vpcs()

        return jsonify({
            "code": 0,
            "msg": f"获取成功，共 {len(vpcs)} 个 VPC",
            "data": {
                "region": ALIYUN_REGION_ID,
                "vpcs": [vpc.to_dict() for vpc in vpcs],
                "count": len(vpcs)
            }
        })
    except Exception as e:
        logger.error(f"获取阿里云 VPC 失败：{str(e)}")
        return jsonify({"code": 1, "msg": f"获取失败：{str(e)}", "data": None}), 500


@app.route("/api/v1/aliyun/security-groups", methods=["GET"])
def get_aliyun_security_groups():
    """获取阿里云安全组列表"""
    try:
        ALIYUN_AK = os.getenv("ALIYUN_AK")
        ALIYUN_SK = os.getenv("ALIYUN_SK")
        ALIYUN_REGION_ID = os.getenv("ALIYUN_REGION_ID", "cn-hangzhou")

        if not ALIYUN_AK or not ALIYUN_SK:
            return jsonify({
                "code": 1,
                "msg": "未配置阿里云凭证",
                "data": None
            }), 400

        client = AliyunCloudClient(ALIYUN_AK, ALIYUN_SK, ALIYUN_REGION_ID)
        security_groups = client.get_all_security_groups()

        return jsonify({
            "code": 0,
            "msg": f"获取成功，共 {len(security_groups)} 个安全组",
            "data": {
                "region": ALIYUN_REGION_ID,
                "security_groups": [sg.to_dict() for sg in security_groups],
                "count": len(security_groups)
            }
        })
    except Exception as e:
        logger.error(f"获取阿里云安全组失败：{str(e)}")
        return jsonify({"code": 1, "msg": f"获取失败：{str(e)}", "data": None}), 500


@app.route("/api/v1/aliyun/all-resources", methods=["GET"])
def get_aliyun_all_resources():
    """获取阿里云所有资源（VPC + ECS + 安全组）"""
    try:
        ALIYUN_AK = os.getenv("ALIYUN_AK")
        ALIYUN_SK = os.getenv("ALIYUN_SK")
        ALIYUN_REGION_ID = os.getenv("ALIYUN_REGION_ID", "cn-hangzhou")

        if not ALIYUN_AK or not ALIYUN_SK:
            return jsonify({
                "code": 1,
                "msg": "未配置阿里云凭证",
                "data": None
            }), 400

        client = AliyunCloudClient(ALIYUN_AK, ALIYUN_SK, ALIYUN_REGION_ID)

        # 并发获取所有资源
        vpcs = []
        instances = []
        security_groups = []

        try:
            vpcs = client.get_vpcs()
        except Exception as e:
            logger.warning(f"获取 VPC 失败：{e}")

        try:
            instances = client.get_all_instances()
        except Exception as e:
            logger.warning(f"获取 ECS 失败：{e}")

        try:
            security_groups = client.get_all_security_groups()
        except Exception as e:
            logger.warning(f"获取安全组失败：{e}")

        return jsonify({
            "code": 0,
            "msg": "获取成功",
            "data": {
                "region": ALIYUN_REGION_ID,
                "summary": {
                    "vpc_count": len(vpcs),
                    "ecs_count": len(instances),
                    "security_group_count": len(security_groups),
                    "total": len(vpcs) + len(instances) + len(security_groups)
                },
                "vpcs": [vpc.to_dict() for vpc in vpcs],
                "instances": instances,
                "security_groups": [sg.to_dict() for sg in security_groups]
            }
        })
    except Exception as e:
        logger.error(f"获取阿里云所有资源失败：{str(e)}")
        return jsonify({"code": 1, "msg": f"获取失败：{str(e)}", "data": None}), 500


# 第十七个API接口：档案卡的页面，从数据库读取
@app.route("/api/device_cards")
def check_physical_device_cards():
    # physical_device_cards = get_global_physical_cards()这是从全局变量读取卡片
    get_global_physical_cards()
    physical_device_cards = db_manager.get_all_physical_cards()
    check_cards_type = request.args.get("device", "all")
    try:
        if check_cards_type == "all":
            logger.info("查看所有物理设备的健康档案卡片成功！")
            return jsonify(physical_device_cards), 200
        else:
            for cards in physical_device_cards:
                if cards["name"] == check_cards_type:
                    logger.info(f"正在查看{cards['name']}设备的健康档案卡片...")
                    result = cards
                    logger.info(f"查看{cards['name']}设备的健康档案卡片成功！")
                    return jsonify(result), 200
            # 遍历完所有设备后，如果都不匹配，才返回不存在的错误
            logger.info(f"{check_cards_type}设备的健康档案卡片不存在！")
            return jsonify({"message": f"{check_cards_type}设备的健康档案卡片不存在！"}), 404
    except Exception as e:
        error_msg = str(e)
        logger.error(f"查看健康档案卡片失败：{error_msg}")
        return (
            jsonify(
                {
                    "message": "查看物理设备健康档案卡片失败！",
                    "error": error_msg[:200],
                    "status": "failed",
                }
            ),
            500,
        )


# 第十八个API接口：获取设备的健康状态历史记录
@app.route("/api/health/history/")
@app.route("/api/health/history/<device_name>")
def get_device_health_history(device_name=None):
    try:
        limit = request.args.get("limit", default=20, type=int)
        days = request.args.get("days", default=7, type=int)
        # 原代码：recoard = ...  # 拼写错误：recoard 应为 record
        record = db_manager.get_health_check_history(device_name=device_name, limit=limit, days=days)
        return jsonify({"status": "success", "history_record": len(record), "history": record})
    except Exception as e:
        error_msg = str(e)
        return (
            jsonify(
                {
                    "status": "failed",
                    "error_msg": error_msg[:100],
                    "history_record": 0,
                }
            ),
            500,
        )


# 第十九个API接口：用AI分析单个设备健康检查结果
ALONE_HEALTH_REPORT_CACHE = {}


# CACHE_EXPIRE_SECONDS = 1800 这个是全局变量不用重复定义
@app.route("/api/health/ai/")
def ai_report_about_health():
    if deepseek_assistant is None:
        logger.error("AI报告接口调用失败：deepseek_assistant 未初始化（API Key错误）")
        return (
            jsonify({"code": 500, "message": "Deepseek调用失败,请查看API key", "data": None, "deepseek_status": "N/A"}),
            500,
        )
    try:
        days = request.args.get("days", default=7, type=int)
        device_name = request.args.get("device_name", default=None, type=str)
        if device_name is None:
            return (
                jsonify(
                    {
                        "code": 400,
                        "message": "请指定要分析的设备名称",
                        "data": None,
                        "deepseek_status": "N/A",
                    }
                ),
                400,
            )
        device_name = device_name.strip().upper() if device_name else None
        report = deepseek_assistant.get_deepseek_to_device_health(days=days, device_name=device_name)
        logger.info("AI报告接口调用成功，报告生成完成")
        cache_key = f"device_{device_name}"
        ALONE_HEALTH_REPORT_CACHE[cache_key] = {
            "report_content": report,
            "create_time": datetime.now().timestamp(),  # 时间戳：方便判断是否过期
            "days": days,
        }
        # 3. 成功返回（统一格式）
        return (
            jsonify(
                {
                    "code": 200,
                    "message": "报告生成成功",
                    "data": report,
                    "deepseek_status": "normal",
                    "report_time": datetime.now().isoformat(),
                }
            ),
            200,
        )
    except Exception as e:
        error_msg = str(e)[:100]
        logger.error(f"AI报告接口调用失败：{error_msg}")
        # 4. 失败返回（统一格式）
        return (
            jsonify(
                {"code": 500, "message": "Deepseek调用失败", "data": None, "error_detail": "服务端处理异常，请稍后重试"}
            ),
            500,
        )


@app.route("/api/health/ai/email/send", methods=["POST"])
def send_single_device_to_email():
    if deepseek_assistant is None:
        logger.error("AI报告接口调用失败：deepseek_assistant 未初始化（API Key错误）")
        return (
            jsonify({"code": 500, "message": "Deepseek调用失败,请查看API key", "data": None, "deepseek_status": "N/A"}),
            500,
        )
    try:
        # 先获取参数
        try:  # 前端把存好的天数，当作请求体发送给后端
            datas = request.get_json(force=True, silent=False)
            logger.info("已经成功解析请求体数据！")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"解析前端请求体数据失败{error_msg[:100]}")
            return (
                jsonify({"code": 400, "message": "请求参数错误，请传入合法的JSON数据", "send_status": "fail"}),
                400,
            )
        days = datas.get("days", request.args.get("days", default=7, type=int))
        device_name_way = request.args.get("device_name", default="", type=str)
        device_name = datas.get("device_name", device_name_way.strip().upper())
        cache_key = f"device_{device_name}"
        # 判断缓存字典里有没有这个设备的AI报告
        if cache_key not in ALONE_HEALTH_REPORT_CACHE:
            logger.error(f"发送邮件失败！请先生成{device_name}的AI报告！")
            return (
                jsonify(
                    {"code": 404, "message": f"未找到{device_name}的AI报告，请先生成报告再发送", "send_status": "fail"}
                ),
                404,
            )
        # 判断生成AI报告的设备天数，和该缓存字典里面的设备天数是否一致
        if (
            days != ALONE_HEALTH_REPORT_CACHE[cache_key]["days"]
        ):  # 缓存里的days是数字类型（7/15/30），in是用来判断 “成员是否在列表 / 字典 / 字符串中” 的，用days not in 数字会直接报错：
            logger.error(f"发送邮件失败！请重新设置天数，生成后再发送！")
            return (
                jsonify(
                    {"code": 404, "message": f"未找到近{days}天的AI报告，请先生成报告再发送", "send_status": "fail"}
                ),
                404,
            )
        # 判断是否缓存字典里面的内容是否过期
        data = ALONE_HEALTH_REPORT_CACHE[cache_key]
        now_timestamp = datetime.now().timestamp()
        if now_timestamp - data["create_time"] > CACHE_EXPIRE_SECONDS:
            del ALONE_HEALTH_REPORT_CACHE[cache_key]  # 删除缓存内容
            logger.error(f"发送邮件失败!,已经超过30分钟!请重新获取AI报告内容")
            return (
                jsonify(
                    {"code": 409, "message": f"AI报告已过期（超过30分钟），请重新生成后再发送", "send_status": "fail"}
                ),
                409,  # 缓存过期应该用409 冲突
            )
        # 完成上面三个条件，才可以发送邮箱
        email_sendor = EmailSender(**emali_config.SMTP_CONFIG)
        logger.info(f"与邮箱服务器建立连接成功")
        email_sendor.ai_report_to_email(
            ai_report=data["report_content"],
            recipient_emails=emali_config.RECIPIENT_EMAILS,
            report_type=f"设备{device_name},近{days}的健康检查历史AI报告",
        )
        logger.info(f"设备{device_name}近{days}天健康AI报告发送邮箱成功，收件人：{emali_config.RECIPIENT_EMAILS}")
        return (
            jsonify(
                {
                    "code": 200,
                    "message": f"设备{device_name}健康AI报告已成功发送至指定邮箱",
                    "send_status": "success",
                    "devices": device_name,
                    "report_days": days,
                    "recipient_count": len(emali_config.RECIPIENT_EMAILS),
                }
            ),
            200,
        )
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error(f"设备{device_name}健康AI报告发送邮箱失败：{error_msg}")
        return (
            jsonify({"code": 500, "message": "AI报告发送邮箱失败", "send_status": "fail", "error_detail": error_msg}),
            500,
        )


# 第二十个API接口，让AI分析所有的设备的健康状态
ALL_HEALTH_REPORT_CACHE = {}
CACHE_EXPIRE_SECONDS = 1800


@app.route("/api/health/ai/all/")
def ai_health_weekly_report():
    # 复用单设备接口的前置校验逻辑
    if deepseek_assistant is None:
        logger.error("全网健康AI报告接口调用失败：deepseek_assistant 未初始化（API Key错误）")
        return (
            jsonify({"code": 500, "message": "Deepseek调用失败,请查看API key", "data": None, "deepseek_status": "N/A"}),
            500,
        )
    try:
        days = request.args.get("days", default=7, type=int)
        # 调用全设备周报AI分析方法
        health_report = deepseek_assistant.get_deepseek_all_device_health_weekly(days=days)
        cache_key = f"days_{days}"
        # 3. 存入缓存：值为「报告内容+生成时间戳」，用于后续判断过期
        ALL_HEALTH_REPORT_CACHE[cache_key] = {
            "report_content": health_report,
            "create_time": datetime.now().timestamp(),  # 时间戳：方便判断是否过期
        }
        logger.info(f"全网设备近{days}天健康AI报告接口调用成功，报告生成完成")
        # 统一返回格式（和单设备一致，含report_time）
        return (
            jsonify(
                {
                    "code": 200,
                    "message": "全网健康AI报告生成成功",
                    "data": health_report,
                    "deepseek_status": "normal",
                    "report_time": datetime.now().isoformat(),
                }
            ),
            200,
        )
    except Exception as e:
        error_msg = str(e)[:100]
        logger.error(f"全网健康AI报告接口调用失败：{error_msg}")
        # 统一500返回格式，补全所有字段
        return (
            jsonify(
                {
                    "code": 500,
                    "message": "Deepseek调用失败",
                    "data": None,
                    "deepseek_status": "error",
                    "error_detail": "服务端处理异常，请稍后重试",
                }
            ),
            500,
        )


@app.route("/api/health/ai/all/email/send", methods=["POST"])
def ai_health_weekly_report_send_email():
    if deepseek_assistant is None:
        logger.error(f"调用AI大模型失败，未成功获取AI生成的报告，请查看相关的APIkey")
        return (
            jsonify({"code": 500, "message": "Deepseek调用失败,请查看API key", "data": None, "deepseek_status": "N/A"}),
            500,
        )
    try:
        # 先取出来days参数判断缓存字典里面有没有
        try:
            datas = request.get_json(force=True, silent=False)  # 漏写请求体类型强制解析，传入非法JSON立马报错
            # 没有传入请求体也会强制解析，所以要用一个try语句防止出现错误
        except Exception as e:
            logger.error(f"解析请求体失败：前端未传入合法的JSON数据，错误信息：{str(e)[:100]}")
            return (
                jsonify({"code": 400, "message": "请求参数错误，请传入合法的JSON数据", "send_status": "fail"}),
                400,
            )
        days = datas.get("days", request.args.get("days", default=7, type=int))
        cache_key = f"days_{days}"
        # 先去判断天数这个键是否在缓存字典里面
        if cache_key not in ALL_HEALTH_REPORT_CACHE:
            logger.error(f"发送邮件失败！请先生成近{days}天的AI报告！")
            return (
                jsonify(
                    {"code": 404, "message": f"未找到近{days}天的AI报告，请先生成报告再发送", "send_status": "fail"}
                ),
                404,
            )
        # 判断数据是否过期
        data = ALL_HEALTH_REPORT_CACHE[cache_key]  # 这个结果本质也是个字典
        now_timestamp = datetime.now().timestamp()
        if now_timestamp - data["create_time"] > CACHE_EXPIRE_SECONDS:
            del ALL_HEALTH_REPORT_CACHE[cache_key]  # 删除缓存内容
            logger.error(f"发送邮件失败!,已经超过30分钟!请重新获取AI报告内容")
            return (
                jsonify(
                    {"code": 409, "message": f"AI报告已过期（超过30分钟），请重新生成后再发送", "send_status": "fail"}
                ),
                409,  # 缓存过期应该用409 冲突
            )
        # 符合以上条件，取出报告内容，发送到邮箱
        all_device_health_report = data["report_content"]
        logger.info("已经成功获取到所有设备的健康检查状态，即将发送到邮箱！")
        email_sendor = EmailSender(**emali_config.SMTP_CONFIG)  # 建立好与邮箱服务器的通道
        # 发送邮件！
        email_sendor.ai_report_to_email(
            ai_report=all_device_health_report,
            recipient_emails=emali_config.RECIPIENT_EMAILS,
            report_type=f"所有设备近{days}天的健康状态历史分析",
        )
        logger.info(f"全网设备近{days}天健康AI报告发送邮箱成功，收件人：{emali_config.RECIPIENT_EMAILS}")
        return (
            jsonify(
                {
                    "code": 200,
                    "message": "全网健康AI报告已成功发送至指定邮箱",
                    "send_status": "success",
                    "report_days": days,
                    "recipient_count": len(emali_config.RECIPIENT_EMAILS),
                }
            ),
            200,
        )
    except Exception as e:
        error_msg = str(e)[:200]
        logger.error(f"全网健康AI报告发送邮箱失败：{error_msg}")
        return (
            jsonify({"code": 500, "message": "AI报告发送邮箱失败", "send_status": "fail", "error_detail": error_msg}),
            500,
        )


# 导入自动发送邮箱的初始化函数
from core.Email.auto_send_report import auto_send_all_health_report, auto_send_backup_report


def init_scheduler():
    try:
        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            func=auto_send_backup_report,  # func必须传函数名（不加括号），调度器会在指定时间自动调用这个函数
            trigger="cron",
            day_of_week=emali_config.AUTO_SEND_WEEKDAY,
            hour=emali_config.AUTO_SEND_HOUR,
            minute=emali_config.AUTO_SEND_MINUTE,
            args=[emali_config.AI_REPORT_DAYS],  # 不能直接赋值”，而是 APScheduler 的add_job函数把args设计成列表参数
            id="auto_send_backup_reportmonday9am",
            replace_existing=True,
        )
        logger.info(
            f"【定时任务】添加备份报告任务成功（每周{emali_config.AUTO_SEND_WEEKDAY} {emali_config.AUTO_SEND_HOUR}:{emali_config.AUTO_SEND_MINUTE}）"
        )

        scheduler.add_job(
            func=auto_send_all_health_report,  # func必须传函数名（不加括号），调度器会在指定时间自动调用这个函数
            trigger="cron",
            day_of_week=emali_config.AUTO_SEND_WEEKDAY,
            hour=emali_config.AUTO_SEND_HOUR,
            minute=emali_config.AUTO_SEND_MINUTE,
            args=[emali_config.AI_REPORT_DAYS],  # 不能直接赋值”，而是 APScheduler 的add_job函数把args设计成列表参数
            id="auto_send_all_health_reportmonday9am",
            replace_existing=True,
        )
        logger.info(
            f"【定时任务】添加健康报告任务成功（每周{emali_config.AUTO_SEND_WEEKDAY} {emali_config.AUTO_SEND_HOUR}:{emali_config.AUTO_SEND_MINUTE}）"
        )
        scheduler.start()
        # 返回实例 → 把这个“有任务、已启动”的实例交出去
        logging.info("【定时任务】调度器启动成功，后台开始计时")
        return scheduler
    except Exception as e:
        error_msg = str(e)
        logger.error(f"【定时任务】初始化失败！错误：{error_msg[:200]}")  # 新增：捕获错误并输出
        return None


# 下载历史备份的API接口
@app.route("/api/v1/backup/download", methods=["GET"])
def download_backup_file():
    logger.info("准备下载文件...")
    try:
        # 获取路径（Flask已经自动解码URL参数）
        backup_dir = request.args.get("path", "N/A")
        logger.info(f"成功获取备份文件的相对路径：{backup_dir}")
        if not backup_dir or backup_dir == "N/A":
            return (
                jsonify(
                    {
                        "code": 400,
                        "msg": "下载失败：无有效下载路径",
                        "data": None,
                    }
                ),
                400,
            )
        if ".." in backup_dir or os.path.isabs(backup_dir):
            return (
                jsonify(
                    {
                        "code": 403,
                        "msg": '"文件路径非法，禁止访问"',
                        "data": None,
                    }
                ),
                403,
            )
        # 在后端拼接绝对路径
        real_backup_file = os.path.join(ROOT_DIR, backup_dir)
        logger.info(f"完整文件路径: {real_backup_file}")
        
        # 看他是否存在，判断它是否是一个文件，不是文件夹
        if not os.path.exists(real_backup_file) or not os.path.isfile(real_backup_file):
            # 列出backupN1目录中的文件供调试
            backup_dir_path = os.path.join(ROOT_DIR, "backupN1")
            if os.path.exists(backup_dir_path):
                files = os.listdir(backup_dir_path)
                logger.info(f"backupN1目录中的文件: {files}")
            return jsonify({"code": 404, "msg": f"备份文件不存在：{real_backup_file}", "data": None}), 404
        
        file_dir = os.path.dirname(real_backup_file)
        file_name = os.path.basename(real_backup_file)
        
        # 使用 send_file 代替 send_from_directory，添加更多控制
        return send_file(
            real_backup_file,
            mimetype='text/plain; charset=utf-8',
            as_attachment=True,
            download_name=file_name,
            max_age=0
        )
    except Exception as e:
        logger.info(f"文件下载失败: {e}")
        return jsonify({"code": 500, "msg": f"下载失败：{str(e)}", "data": None}), 500


# 厂商映射表
VENDOR_MAP = {"华三H3C": "hp_comware", "思科Cisco": "cisco_ios", "华为Huawei": "huawei"}
# 引入校验ipv4的工具函数
from utils.valid_ipv4 import is_valid_ipv4


@app.route("/api/save_device", methods=["POST"])
def save_device():
    try:
        try:
            device_data = request.get_json(force=True, silent=False)  # 请求体类型无标注强制解析，非法请求体直接报错
            logger.info("获取设备信息成功")
        except Exception as e:
            logger.error(f"获取设备信息出现错误：{str(e)[:100]}")
            return jsonify(
                {
                    "code": 1,
                    "msg": f"非法请求体，请检查输入内容{str(e)[:100]}",
                }
            )

        device_name = device_data.get("device_name").strip()
        # 如果前端设备名字传的纯空格，这里去空以后会变成空字符串""，后面有拦截的
        hostname = device_data.get("hostname").strip()
        # 给参数做strip()去空，核心原因正是要让写入配置文件的数据是「干净、有效的」
        username = device_data.get("username").strip()
        password = device_data.get("password").strip()
        vendor = device_data.get("vendor", "华三H3C").strip()
        device_type = VENDOR_MAP[vendor]
        secret = device_data.get("secret", "").strip()
        port_str = device_data.get("port", "22").strip()
        ip_valid, ip_msg = is_valid_ipv4(hostname)
        if not ip_valid:
            return jsonify({"code": 1, "msg": f"IP地址校验失败：{ip_msg}"})
        if not port_str.isdigit():
            logger.warning("端口号未输入纯数字！")
            return jsonify({"code": 1, "msg": "请输入纯数字的端口号"})
        port = int(port_str)
        if not (1 <= port <= 65535):
            logger.warning("未输入有效范围的端口号")
            return jsonify({"code": 1, "msg": "输入的端口号范围不在（1~65535）之间，请输入有效范围的端口号"})
        if not all(
            [device_name, hostname, username, password],
        ):
            return jsonify({"code": 1, "msg": "请输入设备名称，IP,用户名，密码"})
        device_config = {
            "username": username,
            "hostname": hostname,
            "password": password,
            "connection_options": {
                "netmiko": {
                    "extras": {
                        "device_type": device_type,
                        "port": port,
                    },
                },
            },
            "data": {
                "vendor": vendor,
            },
        }
        if vendor == "思科Cisco" and secret:
            device_config["secret"] = secret
        device = {}
        # 判断设备清单存不存在
        if not os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump({}, f)  # 传给一个空字典的形式，为了上面解析的时候不是返回None,返回的也是空字典
        # 读取文件转换为字典
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            device = yaml.safe_load(f) or {}  # 如果里面没有就返回空字典
        # 追加更新
        device[device_name] = device_config
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(device, f, default_flow_style=False, allow_unicode=True, indent=2, sort_keys=False)
            # default_flow_style=False让每个键值对单独占一行，而非挤在一行，可读性拉满强制使用「块格式」（换行）
            # allow_unicode=True支持 Unicode 字符（中文）当设备配
            # sort_keys=False保持字典键的顺序，不自动排序
        return jsonify({"code": 0, "msg": f"设备{device_name}保存成功！"})

    except Exception as e:
        return jsonify({"code": 2, "msg": f"保存失败：{str(e)}"})


@app.route("/api/devices", methods=["GET"])
def get_devices_api():
    try:
        devices = get_devices()
        return jsonify({"code": 0, "data": devices})
    except Exception as e:
        logger.error(f"获取设备列表失败：{str(e)}")
        return jsonify({"code": 1, "msg": f"获取设备列表失败：{str(e)}"})


@app.route("/api/delete_device/<device_name>", methods=["DELETE"])
def delete_device(device_name):
    try:
        if not os.path.exists(CONFIG_PATH):
            return jsonify({"code": 1, "msg": "设备清单文件不存在"})
        
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            device = yaml.safe_load(f) or {}
        
        if device_name not in device:
            return jsonify({"code": 1, "msg": "设备不存在"})
        
        del device[device_name]
        
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(device, f, default_flow_style=False, allow_unicode=True, indent=2, sort_keys=False)
        
        return jsonify({"code": 0, "msg": f"设备{device_name}删除成功！"})
    except Exception as e:
        logger.error(f"删除设备失败：{str(e)}")
        return jsonify({"code": 2, "msg": f"删除失败：{str(e)}"})


# ============================================================
# 用户自定义命令功能（质变级优化 #1）
# ============================================================

# 命令白名单 - 防止注入攻击，只允许安全的查询命令
COMMAND_WHITELIST = {
    # H3C / HP Comware 命令
    "h3c": {
        "display": [
            "display interface brief",           # 接口简要信息
            "display interface",                 # 接口详细信息
            "display ip interface brief",        # IP接口简要信息
            "display ip routing-table",          # 路由表
            "display arp",                       # ARP表
            "display mac-address",               # MAC地址表
            "display vlan",                      # VLAN信息
            "display vlan brief",                # VLAN简要信息
            "display current-configuration",     # 当前配置
            "display version",                   # 版本信息
            "display device",                    # 设备信息
            "display cpu-usage",                 # CPU使用率
            "display memory",                    # 内存使用情况
            "display environment",               # 环境信息（温度、电源、风扇）
            "display power",                     # 电源状态
            "display fan",                       # 风扇状态
            "display temperature",               # 温度信息
            "display logbuffer",                 # 日志缓冲区
            "display trapbuffer",                # Trap缓冲区
            "display ospf peer",                 # OSPF邻居
            "display ospf brief",                # OSPF简要信息
            "display bgp peer",                  # BGP邻居
            "display bgp routing-table",         # BGP路由表
            "display stp",                       # STP信息
            "display stp brief",                 # STP简要信息
            "display link-aggregation summary",  # 链路聚合摘要
            "display port-security",             # 端口安全
            "display dhcp snooping",             # DHCP Snooping
            "display acl all",                   # 所有ACL
            "display ip pool",                   # IP地址池
            "display users",                     # 在线用户
            "display clock",                     # 系统时间
            "display startup",                   # 启动配置
            "display saved-configuration",       # 保存的配置
        ],
        "ping": [
            "ping",                              # Ping命令（需要参数）
        ],
        "tracert": [
            "tracert",                           # Traceroute命令（需要参数）
        ],
    },
    # Cisco IOS 命令
    "cisco": {
        "show": [
            "show ip interface brief",
            "show interfaces",
            "show ip route",
            "show arp",
            "show mac address-table",
            "show vlan",
            "show vlan brief",
            "show running-config",
            "show version",
            "show processes cpu",
            "show memory",
            "show environment all",
            "show power",
            "show fans",
            "show temperature",
            "show logging",
            "show ip ospf neighbor",
            "show ip bgp summary",
            "show spanning-tree",
            "show etherchannel summary",
            "show ip dhcp binding",
            "show access-lists",
            "show users",
            "show clock",
            "show startup-config",
        ],
        "ping": ["ping"],
        "traceroute": ["traceroute"],
    },
    # 华为命令
    "huawei": {
        "display": [
            "display interface brief",
            "display interface",
            "display ip interface brief",
            "display ip routing-table",
            "display arp",
            "display mac-address",
            "display vlan",
            "display current-configuration",
            "display version",
            "display device",
            "display cpu-usage",
            "display memory",
            "display environment",
            "display power",
            "display fan",
            "display temperature",
            "display logbuffer",
            "display ospf peer",
            "display bgp peer",
            "display stp",
            "display link-aggregation summary",
            "display users",
            "display clock",
        ],
        "ping": ["ping"],
        "tracert": ["tracert"],
    },
}

# 命令分类（用于前端展示）
COMMAND_CATEGORIES = {
    "接口相关": ["display interface brief", "display interface", "display ip interface brief",
                   "show ip interface brief", "show interfaces"],
    "路由相关": ["display ip routing-table", "show ip route"],
    "地址表": ["display arp", "display mac-address", "show arp", "show mac address-table"],
    "VLAN信息": ["display vlan", "display vlan brief", "show vlan", "show vlan brief"],
    "系统信息": ["display version", "show version", "display device", "display clock"],
    "性能监控": ["display cpu-usage", "display memory", "show processes cpu", "show memory"],
    "环境状态": ["display environment", "display power", "display fan", "display temperature",
                   "show environment all", "show power", "show fans"],
    "路由协议": ["display ospf peer", "display bgp peer", "show ip ospf neighbor", "show ip bgp summary"],
    "生成树": ["display stp", "display stp brief", "show spanning-tree"],
    "配置管理": ["display current-configuration", "display saved-configuration", "show running-config",
                   "show startup-config"],
    "日志信息": ["display logbuffer", "display trapbuffer", "show logging"],
    "安全相关": ["display port-security", "display dhcp snooping", "display acl all",
                   "show access-lists", "show ip dhcp binding"],
    "链路聚合": ["display link-aggregation summary", "show etherchannel summary"],
    "在线用户": ["display users", "show users"],
}


def validate_command(command, vendor="h3c"):
    """
    验证用户输入的命令是否在白名单中
    返回：(is_valid, error_message, normalized_command)
    """
    if not command or not command.strip():
        return False, "命令不能为空", None

    command = command.strip().lower()

    # 获取对应厂商的命令白名单
    vendor_commands = COMMAND_WHITELIST.get(vendor.lower())
    if not vendor_commands:
        return False, f"不支持的设备厂商：{vendor}", None

    # 检查命令是否在白名单中
    for cmd_prefix, cmd_list in vendor_commands.items():
        for allowed_cmd in cmd_list:
            # 完全匹配 或 用户输入以白名单命令开头（允许带参数）
            if command == allowed_cmd.lower() or command.startswith(allowed_cmd.lower() + " "):
                return True, None, command

    return False, f"命令 '{command}' 不在安全白名单中，不允许执行", None


@app.route("/api/v1/command/whitelist", methods=["GET"])
def get_command_whitelist():
    """获取命令白名单（供前端展示可用命令）"""
    try:
        vendor = request.args.get("vendor", "h3c").lower()
        categories = request.args.get("categories", "true").lower()

        if categories == "true":
            # 返回分类后的命令
            return jsonify({
                "code": 0,
                "msg": "获取成功",
                "data": {
                    "vendor": vendor,
                    "categories": COMMAND_CATEGORIES,
                    "whitelist": COMMAND_WHITELIST.get(vendor, {}),
                }
            })
        else:
            # 返回原始白名单
            return jsonify({
                "code": 0,
                "msg": "获取成功",
                "data": {
                    "vendor": vendor,
                    "whitelist": COMMAND_WHITELIST.get(vendor, {}),
                }
            })
    except Exception as e:
        logger.error(f"获取命令白名单失败：{str(e)}")
        return jsonify({"code": 1, "msg": f"获取失败：{str(e)}", "data": None}), 500


@app.route("/api/v1/command/execute", methods=["POST"])
def execute_custom_command():
    """
    执行用户自定义命令
    请求体：
    {
        "device_name": "SW1",
        "command": "display interface brief",
        "vendor": "h3c"  # 可选，默认从设备配置读取
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"code": 1, "msg": "请求数据为空", "data": None}), 400

        device_name = data.get("device_name")
        command = data.get("command")
        vendor = data.get("vendor", "h3c")

        if not device_name:
            return jsonify({"code": 1, "msg": "设备名称不能为空", "data": None}), 400
        if not command:
            return jsonify({"code": 1, "msg": "命令不能为空", "data": None}), 400

        # 验证命令安全性
        is_valid, error_msg, normalized_cmd = validate_command(command, vendor)
        if not is_valid:
            logger.warning(f"安全警告：用户尝试执行不安全命令 '{command}'，设备：{device_name}")
            return jsonify({"code": 2, "msg": error_msg, "data": None}), 403

        # 获取设备信息
        devices = get_devices()
        target_device = next((d for d in devices if d["device_name"] == device_name), None)
        if not target_device:
            return jsonify({"code": 1, "msg": f"设备 {device_name} 未找到", "data": None}), 404

        # 准备连接参数
        device_copy = target_device.copy()
        device_copy.pop("device_name", None)
        device_copy.pop("vendor", None)

        # 执行命令
        logger.info(f"用户执行自定义命令：设备={device_name}，命令={normalized_cmd}")
        start_time = datetime.now()

        connection = ConnectHandler(**device_copy, timeout=10)
        try:
            output = connection.send_command_timing(normalized_cmd, delay_factor=2)
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            logger.info(f"命令执行成功：设备={device_name}，耗时={execution_time:.2f}秒")

            # 自动保存到命令历史
            try:
                # 从白名单获取命令分类
                command_category = 'unknown'
                for cat, cmds in COMMAND_WHITELIST.get(vendor, {}).items():
                    if normalized_cmd in cmds:
                        command_category = cat
                        break

                history_id = db_manager.save_command_history(
                    device_name=device_name,
                    device_ip=target_device.get('host', ''),
                    command=normalized_cmd,
                    command_category=command_category,
                    result=output,
                    status='success',
                    execution_time=execution_time,
                )
                logger.info(f"命令历史已保存，ID={history_id}")
            except Exception as e:
                logger.warning(f"保存命令历史失败：{e}")

            return jsonify({
                "code": 0,
                "msg": "命令执行成功",
                "data": {
                    "device_name": device_name,
                    "command": normalized_cmd,
                    "output": output,
                    "execution_time": f"{execution_time:.2f}秒",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "history_id": history_id,
                }
            })
        finally:
            connection.disconnect()

    except Exception as e:
        logger.error(f"执行自定义命令失败：{str(e)}")

        # 保存失败记录
        try:
            db_manager.save_command_history(
                device_name=device_name,
                device_ip=target_device.get('host', '') if 'target_device' in locals() else '',
                command=command,
                command_category='unknown',
                result='',
                status='failed',
                error_message=str(e),
            )
        except Exception:
            pass

        return jsonify({"code": 1, "msg": f"执行失败：{str(e)}", "data": None}), 500


@app.route("/api/v1/command/batch-execute", methods=["POST"])
def batch_execute_command():
    """
    批量执行命令（多台设备）
    请求体：
    {
        "device_names": ["SW1", "SW2", "SW3"],
        "command": "display interface brief",
        "vendor": "h3c"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"code": 1, "msg": "请求数据为空", "data": None}), 400

        device_names = data.get("device_names", [])
        command = data.get("command")
        vendor = data.get("vendor", "h3c")

        if not device_names:
            return jsonify({"code": 1, "msg": "设备列表不能为空", "data": None}), 400
        if not command:
            return jsonify({"code": 1, "msg": "命令不能为空", "data": None}), 400

        # 验证命令安全性
        is_valid, error_msg, normalized_cmd = validate_command(command, vendor)
        if not is_valid:
            logger.warning(f"安全警告：用户尝试批量执行不安全命令 '{command}'")
            return jsonify({"code": 2, "msg": error_msg, "data": None}), 403

        # 获取设备列表
        all_devices = get_devices()
        target_devices = [d for d in all_devices if d["device_name"] in device_names]

        if not target_devices:
            return jsonify({"code": 1, "msg": "未找到指定设备", "data": None}), 404

        # 并发执行命令
        results = []
        logger.info(f"批量执行命令：设备数={len(target_devices)}，命令={normalized_cmd}")

        def execute_on_device(device):
            device_copy = device.copy()
            device_copy.pop("device_name", None)
            device_copy.pop("vendor", None)

            try:
                connection = ConnectHandler(**device_copy, timeout=10)
                try:
                    start_time = datetime.now()
                    output = connection.send_command_timing(normalized_cmd, delay_factor=2)
                    end_time = datetime.now()
                    execution_time = (end_time - start_time).total_seconds()

                    return {
                        "device_name": device["device_name"],
                        "status": "成功",
                        "output": output,
                        "execution_time": f"{execution_time:.2f}秒",
                    }
                finally:
                    connection.disconnect()
            except Exception as e:
                return {
                    "device_name": device["device_name"],
                    "status": "失败",
                    "output": None,
                    "error": str(e),
                }

        # 使用线程池并发执行
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(execute_on_device, dev): dev for dev in target_devices}
            for future in as_completed(futures):
                results.append(future.result())

        # 统计结果
        success_count = sum(1 for r in results if r["status"] == "成功")
        fail_count = sum(1 for r in results if r["status"] == "失败")

        logger.info(f"批量执行完成：成功={success_count}，失败={fail_count}")

        return jsonify({
            "code": 0,
            "msg": f"批量执行完成：成功 {success_count} 台，失败 {fail_count} 台",
            "data": {
                "command": normalized_cmd,
                "total": len(results),
                "success": success_count,
                "failed": fail_count,
                "results": results,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        })

    except Exception as e:
        logger.error(f"批量执行命令失败：{str(e)}")
        return jsonify({"code": 1, "msg": f"执行失败：{str(e)}", "data": None}), 500


# ============================================================
# 命令执行历史 API
# ============================================================

# 获取命令历史列表
@app.route("/api/v1/command/history", methods=["GET"])
def get_command_history_list():
    """
    获取命令执行历史列表
    参数：device_name（可选）, command（可选）, limit（可选，默认50）
    """
    try:
        device_name = request.args.get('device_name')
        command = request.args.get('command')
        limit = int(request.args.get('limit', 50))

        history = db_manager.get_command_history(
            device_name=device_name,
            command=command,
            limit=limit,
        )

        return jsonify({
            "code": 0,
            "msg": "success",
            "data": history
        })
    except Exception as e:
        logger.error(f"获取命令历史失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 获取命令历史详情
@app.route("/api/v1/command/history/<int:history_id>", methods=["GET"])
def get_command_history_detail(history_id):
    """获取命令历史详情（包含完整结果）"""
    try:
        detail = db_manager.get_command_history_detail(history_id)
        if detail:
            return jsonify({"code": 0, "msg": "success", "data": detail})
        return jsonify({"code": 1, "msg": "记录不存在", "data": None}), 404
    except Exception as e:
        logger.error(f"获取命令历史详情失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 对比两次命令结果
@app.route("/api/v1/command/compare", methods=["POST"])
def compare_command_results():
    """
    对比两次命令执行结果
    请求体：{"history_id_1": 1, "history_id_2": 2}
    """
    try:
        data = request.get_json()
        history_id_1 = data.get("history_id_1")
        history_id_2 = data.get("history_id_2")

        if not history_id_1 or not history_id_2:
            return jsonify({"code": 1, "msg": "缺少历史记录ID", "data": None}), 400

        result = db_manager.compare_command_results(history_id_1, history_id_2)
        if result:
            return jsonify({"code": 0, "msg": "对比完成", "data": result})
        return jsonify({"code": 1, "msg": "记录不存在", "data": None}), 404
    except Exception as e:
        logger.error(f"对比命令结果失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 下载命令结果
@app.route("/api/v1/command/download/<int:history_id>", methods=["GET"])
def download_command_result(history_id):
    """下载命令执行结果为 TXT 文件"""
    try:
        detail = db_manager.get_command_history_detail(history_id)
        if not detail:
            return jsonify({"code": 1, "msg": "记录不存在", "data": None}), 404

        # 构造文件内容
        content = f"""命令执行结果
====================
设备：{detail['device_name']} ({detail['device_ip']})
命令：{detail['command']}
时间：{detail['created_at']}
状态：{detail['status']}
耗时：{detail.get('execution_time', 'N/A')}秒

执行结果：
====================
{detail['result']}
"""
        if detail.get('error_message'):
            content += f"\n错误信息：{detail['error_message']}"

        # 返回文件
        from flask import Response
        filename = f"{detail['device_name']}_{detail['command'].replace(' ', '_')}_{detail['created_at']}.txt"
        return Response(
            content,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )
    except Exception as e:
        logger.error(f"下载命令结果失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# ============================================================
# Web 终端 API
# ============================================================

# 创建终端连接
@app.route("/api/v1/terminal/connect", methods=["POST"])
def terminal_connect():
    """
    创建终端连接
    请求体：{"host": "192.168.1.1", "port": 22, "username": "admin", "password": "admin"}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"code": 1, "msg": "请求数据为空", "data": None}), 400

        host = data.get("host")
        port = data.get("port", 22)
        username = data.get("username", "admin")
        password = data.get("password", "")

        if not host:
            return jsonify({"code": 1, "msg": "设备IP不能为空", "data": None}), 400

        # 生成会话 ID
        import uuid
        session_id = str(uuid.uuid4())

        # 创建终端连接
        terminal = terminal_manager.create_terminal(
            session_id=session_id,
            host=host,
            port=port,
            username=username,
            password=password,
        )

        if terminal:
            return jsonify({
                "code": 0,
                "msg": "连接成功",
                "data": {
                    "session_id": session_id,
                    "host": host,
                    "port": port,
                }
            })
        else:
            return jsonify({"code": 1, "msg": "连接失败，请检查IP、端口、用户名、密码", "data": None}), 500

    except Exception as e:
        logger.error(f"创建终端连接失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 执行终端命令
@app.route("/api/v1/terminal/execute", methods=["POST"])
def terminal_execute():
    """
    执行终端命令
    请求体：{"session_id": "xxx", "command": "display version", "wait_time": 2}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"code": 1, "msg": "请求数据为空", "data": None}), 400

        session_id = data.get("session_id")
        command = data.get("command")
        wait_time = data.get("wait_time", 2)

        if not session_id:
            return jsonify({"code": 1, "msg": "会话ID不能为空", "data": None}), 400
        if not command:
            return jsonify({"code": 1, "msg": "命令不能为空", "data": None}), 400

        # 执行命令
        output = terminal_manager.execute_command(session_id, command, wait_time)

        # 保存到命令历史
        try:
            terminal = terminal_manager.get_terminal(session_id)
            if terminal:
                db_manager.save_command_history(
                    device_name=f"Terminal-{terminal.host}",
                    device_ip=terminal.host,
                    command=command,
                    command_category='terminal',
                    result=output,
                    status='success',
                )
        except Exception as e:
            logger.warning(f"保存终端命令历史失败：{e}")

        return jsonify({
            "code": 0,
            "msg": "执行成功",
            "data": {
                "session_id": session_id,
                "command": command,
                "output": output,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        })

    except Exception as e:
        logger.error(f"执行终端命令失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 关闭终端连接
@app.route("/api/v1/terminal/disconnect", methods=["POST"])
def terminal_disconnect():
    """
    关闭终端连接
    请求体：{"session_id": "xxx"}
    """
    try:
        data = request.get_json()
        session_id = data.get("session_id")

        if not session_id:
            return jsonify({"code": 1, "msg": "会话ID不能为空", "data": None}), 400

        terminal_manager.close_terminal(session_id)

        return jsonify({
            "code": 0,
            "msg": "已断开连接",
            "data": {"session_id": session_id}
        })

    except Exception as e:
        logger.error(f"关闭终端连接失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 获取活跃终端会话
@app.route("/api/v1/terminal/sessions", methods=["GET"])
def terminal_sessions():
    """获取所有活跃的终端会话"""
    try:
        sessions = terminal_manager.get_active_sessions()
        return jsonify({
            "code": 0,
            "msg": "success",
            "data": sessions
        })
    except Exception as e:
        logger.error(f"获取终端会话失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# ============================================================
# 实时监控 WebSocket 功能（中优先级 #7）
# ============================================================

# 存储监控任务
monitoring_tasks = {}
monitoring_thread = None
is_monitoring = False


def device_monitoring_task(interval=60):
    """
    设备监控任务（后台线程）
    :param interval: 监控间隔（秒）
    """
    global is_monitoring
    logger.info(f"启动设备监控任务，间隔：{interval}秒")

    while is_monitoring:
        try:
            devices = get_devices()
            results = []

            for device in devices:
                try:
                    # 测试连接
                    device_copy = device.copy()
                    device_copy.pop("device_name", None)
                    device_copy.pop("vendor", None)

                    start_time = datetime.now()
                    connection = ConnectHandler(**device_copy, timeout=5)
                    connection.disconnect()
                    end_time = datetime.now()
                    response_time = (end_time - start_time).total_seconds()

                    results.append({
                        "device_name": device["device_name"],
                        "host": device["host"],
                        "status": "online",
                        "response_time": f"{response_time:.2f}秒",
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                except Exception as e:
                    results.append({
                        "device_name": device["device_name"],
                        "host": device["host"],
                        "status": "offline",
                        "error": str(e)[:100],
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })

            # 通过 WebSocket 推送监控结果
            socketio.emit('monitoring_update', {
                'devices': results,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'interval': interval
            })

            # 统计信息
            online_count = sum(1 for r in results if r["status"] == "online")
            offline_count = sum(1 for r in results if r["status"] == "offline")

            socketio.emit('monitoring_stats', {
                'total': len(results),
                'online': online_count,
                'offline': offline_count,
                'health_rate': f"{(online_count / len(results) * 100):.1f}%" if results else "N/A"
            })

            logger.info(f"监控完成：在线={online_count}，离线={offline_count}")

        except Exception as e:
            logger.error(f"监控任务异常：{e}")

        # 等待下一次监控
        socketio.sleep(interval)


@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    logger.info(f"WebSocket 客户端连接：{request.sid}")
    emit('connection_response', {'status': 'connected', 'message': '连接成功'})


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    logger.info(f"WebSocket 客户端断开：{request.sid}")


@socketio.on('start_monitoring')
def handle_start_monitoring(data):
    """开始监控"""
    global is_monitoring, monitoring_thread

    interval = data.get('interval', 60)
    logger.info(f"收到开始监控请求，间隔：{interval}秒")

    if is_monitoring:
        emit('monitoring_status', {'status': 'already_running', 'message': '监控已在运行中'})
        return

    is_monitoring = True
    monitoring_thread = socketio.start_background_task(target=device_monitoring_task, interval=interval)

    emit('monitoring_status', {'status': 'started', 'message': f'监控已启动，间隔：{interval}秒'})


@socketio.on('stop_monitoring')
def handle_stop_monitoring():
    """停止监控"""
    global is_monitoring
    logger.info("收到停止监控请求")

    is_monitoring = False
    emit('monitoring_status', {'status': 'stopped', 'message': '监控已停止'})


@socketio.on('get_monitoring_status')
def handle_get_monitoring_status():
    """获取监控状态"""
    emit('monitoring_status', {
        'status': 'running' if is_monitoring else 'stopped',
        'is_monitoring': is_monitoring
    })


@app.route("/api/v1/monitoring/start", methods=["POST"])
def start_monitoring():
    """启动监控（HTTP API）"""
    try:
        data = request.get_json() or {}
        interval = data.get('interval', 60)

        # 通知所有 WebSocket 客户端
        socketio.emit('start_monitoring', {'interval': interval})

        return jsonify({
            "code": 0,
            "msg": f"监控启动请求已发送，间隔：{interval}秒",
            "data": {"interval": interval}
        })
    except Exception as e:
        logger.error(f"启动监控失败：{e}")
        return jsonify({"code": 1, "msg": f"启动失败：{str(e)}", "data": None}), 500


@app.route("/api/v1/monitoring/stop", methods=["POST"])
def stop_monitoring():
    """停止监控（HTTP API）"""
    try:
        socketio.emit('stop_monitoring')

        return jsonify({
            "code": 0,
            "msg": "监控停止请求已发送",
            "data": None
        })
    except Exception as e:
        logger.error(f"停止监控失败：{e}")
        return jsonify({"code": 1, "msg": f"停止失败：{str(e)}", "data": None}), 500


# ============================================================
# 配置对比与回滚 API（中优先级 #6）
# ============================================================

@app.route("/api/v1/config/versions/<hostname>", methods=["GET"])
def get_config_versions(hostname):
    """获取设备的配置版本列表"""
    try:
        limit = request.args.get("limit", 10, type=int)
        versions = db_manager.get_config_versions(hostname, limit)

        return jsonify({
            "code": 0,
            "msg": f"获取成功，共 {len(versions)} 个版本",
            "data": {
                "hostname": hostname,
                "versions": versions
            }
        })
    except Exception as e:
        logger.error(f"获取配置版本失败：{e}")
        return jsonify({"code": 1, "msg": f"获取失败：{str(e)}", "data": None}), 500


@app.route("/api/v1/config/compare", methods=["POST"])
def compare_configs():
    """对比两个配置版本"""
    try:
        data = request.get_json()
        version_id1 = data.get("version_id1")
        version_id2 = data.get("version_id2")

        if not version_id1 or not version_id2:
            return jsonify({"code": 1, "msg": "请提供两个版本ID", "data": None}), 400

        result = db_manager.compare_configs(version_id1, version_id2)

        if result is None:
            return jsonify({"code": 1, "msg": "版本不存在", "data": None}), 404

        return jsonify({
            "code": 0,
            "msg": "对比完成",
            "data": result
        })
    except Exception as e:
        logger.error(f"配置对比失败：{e}")
        return jsonify({"code": 1, "msg": f"对比失败：{str(e)}", "data": None}), 500


@app.route("/api/v1/config/content/<int:version_id>", methods=["GET"])
def get_config_content(version_id):
    """获取指定版本的配置内容"""
    try:
        content = db_manager.get_config_content(version_id)

        if content is None:
            return jsonify({"code": 1, "msg": "版本不存在", "data": None}), 404

        return jsonify({
            "code": 0,
            "msg": "获取成功",
            "data": {
                "version_id": version_id,
                "content": content
            }
        })
    except Exception as e:
        logger.error(f"获取配置内容失败：{e}")
        return jsonify({"code": 1, "msg": f"获取失败：{str(e)}", "data": None}), 500


# ============================================================
# 效率对比数据 API（中优先级 #10）
# ============================================================

@app.route("/api/v1/efficiency/stats", methods=["GET"])
def get_efficiency_stats():
    """获取效率对比数据"""
    try:
        # 从数据库获取实际数据
        backup_records = db_manager.get_recent_backups(limit=100)
        health_records = db_manager.get_health_check_history(limit=100)

        # 计算效率数据
        backup_stats = {
            "total_backups": len(backup_records),
            "avg_duration": 0,
            "success_rate": 0,
            "time_saved": 0
        }

        if backup_records:
            durations = [r.get("duration", 0) for r in backup_records if r.get("duration")]
            if durations:
                backup_stats["avg_duration"] = sum(durations) / len(durations)

            success_count = sum(1 for r in backup_records if r.get("status") == "success")
            backup_stats["success_rate"] = (success_count / len(backup_records)) * 100

            # 假设手动备份每台需要5分钟，自动化每台需要30秒
            backup_stats["time_saved"] = len(backup_records) * 4.5  # 分钟

        health_stats = {
            "total_checks": len(health_records),
            "avg_duration": 0,
            "success_rate": 0,
            "time_saved": 0
        }

        if health_records:
            success_count = sum(1 for r in health_records if r.get("check_status") == "成功")
            health_stats["success_rate"] = (success_count / len(health_records)) * 100

            # 假设手动检查每台需要3分钟，自动化每台需要20秒
            health_stats["time_saved"] = len(health_records) * 2.67  # 分钟

        return jsonify({
            "code": 0,
            "msg": "获取成功",
            "data": {
                "backup": backup_stats,
                "health_check": health_stats,
                "efficiency_comparison": {
                    "manual_backup_time": "5分钟/台",
                    "auto_backup_time": "30秒/台",
                    "manual_health_check_time": "3分钟/台",
                    "auto_health_check_time": "20秒/台",
                    "backup_efficiency": "10倍提升",
                    "health_check_efficiency": "9倍提升"
                }
            }
        })
    except Exception as e:
        logger.error(f"获取效率数据失败：{e}")
        return jsonify({"code": 1, "msg": f"获取失败：{str(e)}", "data": None}), 500


# ============================================================
# 拓扑相关 API（一期新增）
# ============================================================

# 获取当前拓扑数据（从数据库读取）
@app.route("/api/v1/topology/data")
def get_topology_data():
    try:
        nodes = db_manager.get_all_topology_nodes()
        links = db_manager.get_all_topology_links()
        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "nodes": nodes,
                "links": links,
                "metadata": {
                    "device_count": len(nodes),
                    "link_count": len(links),
                }
            }
        })
    except Exception as e:
        logger.error(f"获取拓扑数据失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 触发拓扑扫描（SNMP 采集）
@app.route("/api/v1/topology/scan", methods=["POST"])
def scan_topology():
    """
    触发拓扑扫描
    POST 参数：
    - seed_ip: 种子设备IP（必填）
    - community: SNMP团体名（默认public）
    - scan_mode: 扫描模式 single/multi（默认single）
    - max_depth: 最大扫描深度（默认3，仅multi模式有效）
    - snmp_version: SNMP版本 v2c/v3（默认v2c）
    - username: v3用户名
    - auth_protocol: v3认证协议 md5/sha/none
    - auth_password: v3认证密码
    - priv_protocol: v3加密协议 des/aes/none
    - priv_password: v3加密密码
    """
    try:
        data = request.get_json() or {}
        seed_ip = data.get("seed_ip")
        community = data.get("community", "public")
        scan_mode = data.get("scan_mode", "single")  # single=单层, multi=多层BFS
        max_depth = data.get("max_depth", 3)
        snmp_version = data.get("snmp_version", "v2c")

        # v3 参数
        username = data.get("username", "")
        auth_protocol = data.get("auth_protocol", "none")
        auth_password = data.get("auth_password", "")
        priv_protocol = data.get("priv_protocol", "none")
        priv_password = data.get("priv_password", "")

        if not seed_ip:
            return jsonify({"code": 1, "msg": "缺少种子设备IP", "data": None}), 400

        if not PYSNMP_AVAILABLE:
            return jsonify({"code": 1, "msg": "pysnmp 没装，SNMP 功能用不了", "data": None}), 500

        # 用 asyncio 跑 SNMP 采集
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        builder = TopologyBuilder()

        try:
            if scan_mode == 'mac_fallback':
                # MAC 回退模式：先用 LLDP，失效时用 MAC 表推导（创新点！）
                logger.info(f"启动 MAC 回退扫描模式，种子：{seed_ip}，最大深度：{max_depth}")
                loop.run_until_complete(builder.build_topology_with_mac_fallback(
                    seed_ip, community=community, max_depth=max_depth,
                    snmp_version=snmp_version,
                    username=username, auth_protocol=auth_protocol,
                    auth_password=auth_password, priv_protocol=priv_protocol,
                    priv_password=priv_password,
                ))
            elif scan_mode == 'multi':
                # 多层扫描模式：广度优先，自动发现邻居的邻居
                logger.info(f"启动多层扫描模式，种子：{seed_ip}，最大深度：{max_depth}")
                loop.run_until_complete(builder.build_topology_bfs(
                    seed_ip, community=community, max_depth=max_depth,
                    snmp_version=snmp_version,
                    username=username, auth_protocol=auth_protocol,
                    auth_password=auth_password, priv_protocol=priv_protocol,
                    priv_password=priv_password,
                ))
            else:
                # 单层扫描模式：只扫描种子设备的邻居（原有逻辑）
                logger.info(f"启动单层扫描模式，种子：{seed_ip}")
                if snmp_version == 'v3':
                    collector = SNMPCollector(
                        seed_ip, version='v3',
                        username=username, auth_protocol=auth_protocol,
                        auth_password=auth_password, priv_protocol=priv_protocol,
                        priv_password=priv_password,
                    )
                else:
                    collector = SNMPCollector(seed_ip, community=community)
                collected_data = loop.run_until_complete(collector.collect_all())
                builder.build_from_lldp(seed_ip, collected_data)
        finally:
            loop.close()

        # 保存到数据库
        db_manager.clear_topology_nodes()
        db_manager.clear_topology_links()

        nodes_list = builder.get_nodes_list()
        links_list = builder.get_links_list()

        db_manager.batch_save_topology_nodes(nodes_list)
        db_manager.batch_save_topology_links(links_list)

        logger.info(f"拓扑扫描完成：{len(nodes_list)} 个节点，{len(links_list)} 条链路")

        return jsonify({
            "code": 0,
            "msg": f"扫描完成（{scan_mode}模式）",
            "data": {
                "nodes": nodes_list,
                "links": links_list,
                "metadata": {
                    "device_count": len(nodes_list),
                    "link_count": len(links_list),
                    "seed_ip": seed_ip,
                    "scan_mode": scan_mode,
                    "max_depth": max_depth if scan_mode == 'multi' else 1,
                    "snmp_version": snmp_version,
                }
            }
        })
    except Exception as e:
        logger.error(f"拓扑扫描失败：{e}")
        return jsonify({"code": 1, "msg": f"扫描失败：{str(e)}", "data": None}), 500


# 保存当前拓扑为快照
@app.route("/api/v1/topology/snapshot", methods=["POST"])
def save_snapshot():
    """保存当前拓扑快照"""
    try:
        data = request.get_json() or {}
        snapshot_name = data.get("name", f"快照_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        nodes = db_manager.get_all_topology_nodes()
        links = db_manager.get_all_topology_links()

        snapshot_id = db_manager.save_topology_snapshot(snapshot_name, nodes, links)

        return jsonify({
            "code": 0,
            "msg": "快照保存成功",
            "data": {"snapshot_id": snapshot_id, "name": snapshot_name}
        })
    except Exception as e:
        logger.error(f"保存快照失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 获取快照列表
@app.route("/api/v1/topology/snapshots")
def get_snapshots():
    try:
        snapshots = db_manager.get_topology_snapshots()
        return jsonify({"code": 0, "msg": "success", "data": snapshots})
    except Exception as e:
        logger.error(f"获取快照列表失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 获取某个快照详情
@app.route("/api/v1/topology/snapshot/<int:snapshot_id>")
def get_snapshot_detail(snapshot_id):
    try:
        snapshot = db_manager.get_topology_snapshot_detail(snapshot_id)
        if snapshot:
            return jsonify({"code": 0, "msg": "success", "data": snapshot})
        return jsonify({"code": 1, "msg": "快照不存在", "data": None}), 404
    except Exception as e:
        logger.error(f"获取快照详情失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# ============================================================
# 配置导出/导入 API
# ============================================================

# 导出项目配置
@app.route("/api/v1/config/export", methods=["GET"])
def export_config():
    """
    导出项目配置文件（设备清单 + SNMP配置）
    方便换环境时一键导入
    """
    try:
        # 读取设备清单
        devices = get_devices()

        # 构造导出数据
        export_data = {
            'export_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'version': 'V8.0',
            'devices': devices,
            'snmp_config': {
                'default_community': 'public',
                'default_version': 'v2c',
                'default_port': 161,
            },
            'topology_config': {
                'scan_mode': 'single',
                'max_depth': 3,
            },
        }

        return jsonify({
            "code": 0,
            "msg": "配置导出成功",
            "data": export_data
        })
    except Exception as e:
        logger.error(f"导出配置失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 导入项目配置
@app.route("/api/v1/config/import", methods=["POST"])
def import_config():
    """
    导入项目配置文件
    接收 JSON 格式的配置数据，更新设备清单
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"code": 1, "msg": "没有接收到配置数据", "data": None}), 400

        devices = data.get('devices', [])
        if not devices:
            return jsonify({"code": 1, "msg": "配置中没有设备信息", "data": None}), 400

        # 写入设备清单文件
        import yaml

        # 转换为 Nornir 格式
        nornir_config = {}
        for device in devices:
            device_name = device.get('device_name', '')
            if not device_name:
                continue

            nornir_config[device_name] = {
                'hostname': device.get('host', ''),
                'username': device.get('username', ''),
                'password': device.get('password', ''),
                'platform': device.get('device_type', 'huawei'),
                'data': {
                    'vendor': device.get('vendor', 'unknown'),
                },
            }

        # 写入文件
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(nornir_config, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"配置导入成功，共 {len(devices)} 台设备")

        return jsonify({
            "code": 0,
            "msg": f"配置导入成功，共 {len(devices)} 台设备",
            "data": {"device_count": len(devices)}
        })
    except Exception as e:
        logger.error(f"导入配置失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# ============================================================
# SDN 控制器相关 API（二期新增）
# ============================================================

# 测试 SDN 控制器连接
@app.route("/api/v1/sdn/test")
def test_sdn_connection():
    """测试能否连接到 Ryu 控制器"""
    try:
        controller_ip = request.args.get('ip', '127.0.0.1')
        controller_port = int(request.args.get('port', 8080))

        collector = SDNCollector(controller_ip, controller_port)
        result = collector.test_connection()

        return jsonify({"code": 0, "msg": "success", "data": result})
    except Exception as e:
        logger.error(f"SDN 连接测试失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 获取 SDN 拓扑数据
@app.route("/api/v1/sdn/topology")
def get_sdn_topology():
    """从 Ryu 控制器获取 SDN 网络拓扑"""
    try:
        controller_ip = request.args.get('ip', '127.0.0.1')
        controller_port = int(request.args.get('port', 8080))

        collector = SDNCollector(controller_ip, controller_port)
        result = collector.collect_all()

        # 保存到数据库
        db_manager.clear_topology_nodes()
        db_manager.clear_topology_links()
        db_manager.batch_save_topology_nodes(result['nodes'])
        db_manager.batch_save_topology_links(result['edges'])

        return jsonify({
            "code": 0,
            "msg": "success",
            "data": {
                "nodes": result['nodes'],
                "links": result['edges'],
                "metadata": result['metadata'],
                "mode": "sdn"
            }
        })
    except Exception as e:
        logger.error(f"获取 SDN 拓扑失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 获取流表信息
@app.route("/api/v1/sdn/flows")
def get_sdn_flows():
    """获取 OpenFlow 流表"""
    try:
        controller_ip = request.args.get('ip', '127.0.0.1')
        controller_port = int(request.args.get('port', 8080))
        dpid = request.args.get('dpid')

        collector = SDNCollector(controller_ip, controller_port)
        flows = collector.get_flow_stats(int(dpid) if dpid else None)

        return jsonify({"code": 0, "msg": "success", "data": flows})
    except Exception as e:
        logger.error(f"获取流表失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# ============================================================
# 网络小工具 API（二期新增）
# ============================================================

# IP 网段扫描
@app.route("/api/v1/tools/ping-sweep", methods=["POST"])
def ping_sweep():
    """扫描网段内存活主机"""
    try:
        data = request.get_json() or {}
        network = data.get("network")
        start = data.get("start", 1)
        end = data.get("end", 254)

        if not network:
            return jsonify({"code": 1, "msg": "缺少网段参数", "data": None}), 400

        # 限制扫描范围，防止太慢
        if end - start > 254:
            end = start + 254

        alive_hosts = NetworkTools.scan_subnet(network, start=start, end=end)

        return jsonify({
            "code": 0,
            "msg": f"扫描完成，发现 {len(alive_hosts)} 台主机",
            "data": alive_hosts
        })
    except Exception as e:
        logger.error(f"网段扫描失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 端口扫描
@app.route("/api/v1/tools/port-scan", methods=["POST"])
def port_scan():
    """扫描指定主机的开放端口"""
    try:
        data = request.get_json() or {}
        host = data.get("host")
        ports = data.get("ports")

        if not host:
            return jsonify({"code": 1, "msg": "缺少主机参数", "data": None}), 400

        results = NetworkTools.scan_ports(host, ports=ports)

        return jsonify({
            "code": 0,
            "msg": "扫描完成",
            "data": results
        })
    except Exception as e:
        logger.error(f"端口扫描失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# 连通测试
@app.route("/api/v1/tools/ping", methods=["POST"])
def ping_test():
    """Ping 连通测试"""
    try:
        data = request.get_json() or {}
        host = data.get("host")
        count = data.get("count", 2)

        if not host:
            return jsonify({"code": 1, "msg": "缺少主机参数", "data": None}), 400

        result = NetworkTools.ping(host, count=count)

        return jsonify({"code": 0, "msg": "success", "data": result})
    except Exception as e:
        logger.error(f"Ping 测试失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# Traceroute
@app.route("/api/v1/tools/traceroute", methods=["POST"])
def traceroute_test():
    """Traceroute 路径追踪"""
    try:
        data = request.get_json() or {}
        host = data.get("host")
        max_hops = data.get("max_hops", 15)

        if not host:
            return jsonify({"code": 1, "msg": "缺少主机参数", "data": None}), 400

        hops = NetworkTools.traceroute(host, max_hops=max_hops)

        return jsonify({
            "code": 0,
            "msg": f"Traceroute 完成，{len(hops)} 跳",
            "data": hops
        })
    except Exception as e:
        logger.error(f"Traceroute 失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


# LLDP 单设备查询
@app.route("/api/v1/tools/lldp-query", methods=["POST"])
def lldp_query():
    """查询单个设备的 LLDP 邻居"""
    try:
        data = request.get_json() or {}
        host = data.get("host")
        community = data.get("community", "public")

        if not host:
            return jsonify({"code": 1, "msg": "缺少主机参数", "data": None}), 400

        result = NetworkTools.query_device_lldp(host, community=community)

        return jsonify({"code": 0, "msg": "success", "data": result})
    except Exception as e:
        logger.error(f"LLDP 查询失败：{e}")
        return jsonify({"code": 1, "msg": str(e), "data": None}), 500


if __name__ == "__main__":
    logger.info("调度器正在准备加载任务请稍后.......")
    init_scheduler()

    # 使用 socketio 运行，支持 WebSocket
    # allow_unsafe_werkzeug=True 允许在开发模式下使用 Werkzeug
    socketio.run(
        app,
        host="0.0.0.0",
        port=8080,
        debug=True,
        allow_unsafe_werkzeug=True
    )
