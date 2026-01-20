from datetime import datetime
import sys
from database import db_manager
from flask import jsonify, Flask, render_template, request

# 1.jsonify就是为了返回JSON格式的数据
from health_check import check_single_device
from backup import backup_single_device
import yaml
from report_generator import deepseek_assistant
from nornir_tasks import run_concurrent_health_check
from log_setup import setup_logger
import logging
from monitoring import SystemMonitor, get_prometheus_metrics

logger = setup_logger("web_dashboard", "web_dashboard.log")

app = Flask(__name__)


def get_devices(filename="devices.yaml"):
    device_list = []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            for device_name, device_info in data["devices"].items():
                device = {
                    "device_name": device_name,
                    # 1.鱼和熊掌必须兼得」的场景，但「复制字典再删除device_name键值对」
                    # 是实现「二者兼得」的唯一且必要的步骤 **，没有其他更优的替代方案（至少在当前的业务场景下）。
                    # 也就是说如果你想让用户再页面看到SW1，就必须增加这个键值对，但是你调用连接函数的时候，又必须删掉，因为库
                    # 不认识多余的键值对
                    "device_type": device_info["device_type"],
                    "host": device_info["host"],
                    "username": device_info["username"],
                    "password": device_info["password"],
                    "port": 22,
                }
                device_list.append(device)
        return device_list
    except Exception as e:
        logger.error(f"错误：未成功读取设备文件 - {e}")
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
    # host参数，本质上要求传入一个「字符串（str）类型」的值，用来指定 Flask 服务绑定的 IP 地址。0.0.0.0是一个 IP 地址格式的字符串
