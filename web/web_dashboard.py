from ast import Global
from datetime import datetime
import sys
import os
from unittest import result

print(f"当前Python路径：{sys.executable}")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from db.database import db_manager
from flask import jsonify, Flask, render_template, request

# 1.jsonify就是为了返回JSON格式的数据
from core.health_check.health_checker import check_single_device
from core.backup.backup_handler import backup_single_device
import yaml
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

logger = setup_logger("web_dashboard", "web_dashboard.log")

app = Flask(__name__)


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
                device = {
                    "device_name": device_name,  # 保持原有键，兼容后续逻辑
                    "device_type": netmiko_extras.get("device_type", "hp_comware"),  # 从netmiko配置取设备类型
                    "host": device_info.get("hostname", ""),  # 顶层取IP/主机名
                    "username": device_info.get("username", ""),  # 顶层取用户名
                    "password": device_info.get("password", ""),  # 顶层取密码
                    "port": netmiko_extras.get("port", 22),  # 从netmiko配置取端口，默认22
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
    for dev in devices:
        dev["status"] = "在线"
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
    try:
        limit = request.args.get("limit", default=20, type=int)
        recoard = db_manager.get_recent_backups(hostname=device_name, limit=limit)
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
    # host参数，本质上要求传入一个「字符串（str）类型」的值，用来指定 Flask 服务绑定的 IP 地址。0.0.0.0是一个 IP 地址格式的字符串
