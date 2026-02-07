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
from flask import jsonify, Flask, render_template, request, send_from_directory

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

# 引入真实阿里云客户
from core.cloud.real_providers.ali_client import AliyunCloudClient

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

logger = setup_logger("web_dashboard", "web_dashboard.log")

app = Flask(__name__)

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
        backup_single_device(target_device_copy)
        end_time = datetime.now()
        import time

        backup_dir = "backupN1"
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_filename = f"{target_device['host']}__配置__{timestamp}.txt"
        backup_path = f"{backup_dir}/{backup_filename}"
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
        recoard = db_manager.get_recent_backups(hostname=device_name, limit=limit, days=days)
        return jsonify({"status": "success", "history_record": len(recoard), "history": recoard})
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
                    logger.error(f"获取全部真实网络资源失败{e}")
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
        recoard = db_manager.get_health_check_history(device_name=device_name, limit=limit, days=days)
        return jsonify({"status": "success", "history_record": len(recoard), "history": recoard})
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
        backup_dir = request.args.get("path", "N/A")
        logger.info("成功获取备份文件的相对路径！")
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
        # 看他是否存在，判断它是否是一个文件，不是文件夹
        if not os.path.exists(real_backup_file) or not os.path.isfile(real_backup_file):
            return jsonify({"code": 404, "msg": f"备份文件不存在：{real_backup_file}", "data": None}), 404
        file_dir = os.path.dirname(real_backup_file)
        file_name = os.path.basename(real_backup_file)
        return send_from_directory(
            directory=file_dir, path=file_name, as_attachment=True  # 核心：触发浏览器下载，不是展示
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


if __name__ == "__main__":
    logger.info("调度器正在准备加载任务请稍后.......")
    init_scheduler()

    app.run(
        host="0.0.0.0",
        port=8080,
        debug=True,
    )
    # host参数，本质上要求传入一个「字符串（str）类型」的值，用来指定 Flask 服务绑定的 IP 地址。0.0.0.0是一个 IP 地址格式的字符串
    # 这行代码永远执行不到！因为上面的app.run()不会结束（除非手动停服务）因为 app.run() 是「阻塞式」的
    # init_scheduler()
    # logger.info('调度器正在准备加载任务请稍后.......')
