import logging

from log_setup import setup_logger

logger = setup_logger("nornir_tasks", "nornir_tasks.log")
from nornir import InitNornir
from nornir_netmiko import netmiko_send_command
from nornir.core.task import Task, Result

# 第一步：创建控制台实例


# 第二步：定义一个检查健康的主任务，分两个子任务,对一个设备进行检查
def check_devices_health(task: Task) -> Result:
    device_name = task.host.name  # 这个助手已经拿到档案卡片了，控制台已经把host实例绑定到助手上面了
    logger.info(f"正在检查设备{device_name}的健康状态.....")
    try:
        logger.info(f"正在查询设备{device_name}的版本信息.....")
        version_result = task.run(
            task=netmiko_send_command, command_string="display version", name=f"查询版本-{device_name}"
        )
        logger.info(f"查询{device_name}版本信息成功！")
        logger.info(f"正在查询设备{device_name}的接口状态信息....")
        interface_result = task.run(
            task=netmiko_send_command, command_string="display interface brief", name=f"查询接口状态-{device_name}"
        )
        logger.info(f"查询{device_name}接口状态成功！")
        logger.info(version_result.result)
        details = {
            "version_result": version_result.result if version_result.result else "",
            "interface_result": interface_result.result if interface_result.result else "",
            "reachable": True,
        }
        logger.info(f"设备{device_name}检查完毕！")
        is_health = True
        details = {
            "version_result": version_result.result if version_result.result else "",
            "interface_result": interface_result.result if interface_result.result else "",
            "reachable": True,
        }
        logger.info(f"设备{device_name}检查完毕！")
        is_health = True
        return Result(
            host=task.host,
            result={"device_name": device_name, "status": "success" if is_health else "failure", "details": details},
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
        nr = InitNornir(config_file="nornir_config.yaml")  # 加载设备清单，HOST实例也有了
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
