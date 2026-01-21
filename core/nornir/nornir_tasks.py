import re
import os
import sys
import logging
from nornir import InitNornir
from utils.log_setup import setup_logger
from nornir.core.task import Task, Result
from nornir_netmiko import netmiko_send_command


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
CONFIG_PATH1 = os.path.join(ROOT_DIR, "config", "nornir_config.yaml")
logger = setup_logger("nornir_tasks", "nornir_tasks.log")
# 第一步：创建控制台实例


# 第二步：定义一个检查健康的主任务，分两个子任务,对一个设备进行检查
def check_devices_health(task: Task) -> Result:
    device_name = task.host.name  # 这个助手已经拿到档案卡片了，控制台已经把host实例绑定到助手上面了
    logger.info(f"正在检查设备{device_name}的健康状态.....")
    try:
        # 获取版本信息
        logger.info(f"正在查询设备{device_name}的版本信息.....")
        version_result = task.run(
            task=netmiko_send_command, command_string="display version", name=f"查询版本-{device_name}"
        )
        logger.info(f"查询{device_name}版本信息成功！")
        # 查询接口状态
        logger.info(f"正在查询设备{device_name}的接口状态信息....")
        interface_result = task.run(
            task=netmiko_send_command, command_string="display interface brief", name=f"查询接口状态-{device_name}"
        )
        logger.info(f"查询{device_name}接口状态成功！")
        # 查询CPU使用率
        logger.info(f"正在查询设备{device_name}的CPU使用率....")
        CPU_usage_result = task.run(
            task=netmiko_send_command, command_string="display memory-usage", name=f"查询CPU使用率-{device_name}"
        )
        # 查询内存使用率
        logger.info(f"查询{device_name}CPU使用率成功！")
        logger.info(f"正在查询设备{device_name}的内存使用率....")
        memory_usage_result = task.run(
            task=netmiko_send_command, command_string="display cpu-usage", name=f"查询内存使用率-{device_name}"
        )
        logger.info(f"查询{device_name}内存使用率成功！")
        # 1.分析接口状态
        output_inteface = interface_result.result

        total_ports = 0
        down_ports = 0
        up_ports = 0
        critical_ports_down = False
        lines = output_inteface.split("\n")
        data_start = 0
        for i, line in enumerate(lines):
            # 找到数据的开始行
            if "Interface" in line and "Protocol" in line:
                data_start = i + 1
                logger.info(f"找到表头在{data_start}行")
                break
        if data_start == 0:
            data_start = 18
            logger.info(f"找到表头在{data_start}行")
        for line in lines[data_start:]:
            line_clean = line.strip().upper()
            if not line_clean:
                continue
            if "UP" in line_clean and "DOWN" not in line_clean:
                up_ports += 1
            elif "DOWN" in line_clean:
                down_ports += 1
                if line_clean.startswith("GE1/0/1 "):
                    critical_ports_down = True
                    logger.info(f"端口 GE1/0/1 状态为DOWN")
                    logger.warning(f"关键端口 GE1/0/1 已DOWN")
        total_ports = up_ports + down_ports
        # 2.分析CPU使用率
        CPU_usage = CPU_usage_result.result
        CPU_lines = CPU_usage.split("\n")
        CPU_usage_high = False
        for line in CPU_lines:
            line_clean = line.strip()
            if not line_clean:
                continue
            if "seconds" in line_clean:
                match = re.search(r"(\d+)%", line_clean)
                # 正则表达式匹配的是「文本字符」，不管字符看起来像数字还是字母，提取结果本质都是字符串
                if match and int(match.group(1)) > 88:
                    CPU_usage_high = True
        # 3.分析内存使用率
        memory_usage = memory_usage_result.result
        memory_lines = memory_usage.split("\n")
        memory_usage_high = False
        for line in memory_lines:
            line_clean = line.strip()
            if not line_clean:
                continue
            if "Memory" in line and "usage" in line:
                match = re.search(r"(\d+)%", line)
                if match and int(match.group(1)) > 88:
                    memory_usage_high = True
        # 4.判断设备是否健康
        is_health = True
        device_health_issues = []
        if critical_ports_down:
            is_health = False
            device_health_issues.append("关键端口DOWN")
        if down_ports / total_ports > 0.3:  # 超过百分之30的端口都是down
            is_health = False
            device_health_issues.append(f"过多端口down ({down_ports}/{total_ports})")
        if CPU_usage_high:
            is_health = False
            device_health_issues.append("CPU使用率过高，已经超过88%")
        if memory_usage_high:
            is_health: False
            device_health_issues.append("内存使用率过高，已经超过88%")

        # 收集结果
        details = {
            "version_result": version_result.result if version_result.result else "",
            "interface_result": interface_result.result if interface_result.result else "",
            "interfaces_total": total_ports,
            "interfaces_down": down_ports,
            "CPU_usage_result": "告警！" if CPU_usage_high else "正常，未超过88%",
            "memory_usage_result": "告警！" if memory_usage_high else "正常，未超过88%",
            "device_health_issues": device_health_issues if device_health_issues else "无",
            "reachable": True,
        }
        status = "healthy" if is_health else "degraded"  # 质量下降的、性能退化的
        logger.info(f"设备{device_name}检查完成，状态: {status}, 问题: {device_health_issues}")
        return Result(
            host=task.host,
            result={
                "device_name": device_name,
                "status": status,
                "details": details,
                "device_health_issues": device_health_issues,
            },
        )  # task.host（Host实例）会被存入Result对象的专属属性中
    except Exception as e:
        logger.error(f"检查设备时出现错误 {e}")
        error_msg = str(e)
        return Result(
            host=task.host,
            result={
                "device_name": device_name,
                "status": "failed",
                "error": error_msg[:100],
            },
            failed=True,
        )


# 第三步：检查设备健康的总调度员（主函数）
def run_concurrent_health_check(hosts=None):
    try:
        nr = InitNornir(config_file=CONFIG_PATH1)  # 加载设备清单，HOST实例也有了
        logger.info("Nornir实例初始化成功！")
    except Exception as e:
        logger.error(f"Nornir实例初始化失败{e}")
        nr = None
    if nr is None:
        logger.error("Nornir实例初始化失败,请检查相关配置")
        return {"error": "Nornir框架初始化失败"}
    target_nr = nr
    if hosts:
        logger.info(f"筛选目标设备{hosts}.....")
        target_nr = nr.filter(filter_func=lambda h: h.name in hosts)
        original_devices = list(nr.inventory.hosts.keys())
        logger.info(f"Nornir原始设备列表：{original_devices}")
        true_device = list(target_nr.inventory.hosts.keys())
        logger.info(f"已筛选出设备{true_device}")

    logger.info(f"共有{len(target_nr.inventory.hosts)}台设备并发执行！")
    try:
        result = target_nr.run(task=check_devices_health)

        standardized_results = {"success": [], "failed": []}
        for host_name, multi_results in result.items():
            health_result = multi_results[0]  # 这是一台一台的遍历，这里就是主任务
            if health_result.failed:
                standardized_results["failed"].append(
                    {"hostname": host_name, "error": health_result.result.get("error", "未知错误")}
                )
            else:
                standardized_results["success"].append({"hostname": host_name, "result": health_result.result})
        summary = f"并发检查设备完成！共计：{len(result)},成功：{len(standardized_results['success'])},失败：{len(standardized_results['failed'])}"
        standardized_results["summary"] = summary
        logger.info(summary)
        return standardized_results
    except Exception as e:
        error_msg = str(e)
        logger.error(f"并发检查执行失败！{error_msg[:50]}")
        return {"error": f"并发检查设备任务失败{error_msg[:50]}"}
