import os
import argparse
import re
from netmiko import ConnectHandler
import yaml
from log_setup import setup_logger

logger = setup_logger("netdevops_health_check", "health_check.log")


# 第一步：定义可以读取yml文件的函数
def read_devices_yml(filename="devices.yaml", yaml_connect=None):
    device_list = []
    try:
        if yaml_connect:
            data = yaml.safe_load(yaml_connect)  # 解析空白字符串 → data = None
        else:
            with open(filename, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        if data != None:
            for device_name, device_info in data["devices"].items():  # data = None 就会出错
                devices = {
                    "device_type": device_info["device_type"],
                    "host": device_info["host"],
                    "username": device_info["username"],
                    "password": device_info["password"],
                    "port": 22,
                }
                logger.info(f"-已经读取{device_name}  ({device_info['host']})\n")
                device_list.append(devices)
            return device_list
        else:
            return device_list

    except FileNotFoundError:
        logger.critical("错误：未找到对应文件！")
        return device_list
    except KeyError as e:
        logger.critical(f"错误：相应文件内键值存在问题  {e}")
        return device_list
    except yaml.YAMLError as e:
        logger.critical(f"错误：未成功解析相应的文件！ {e}")
        return device_list


# 第二步：检查接口的状态
def check_interface_status(connections):
    error_massage = ""
    try:
        output_interfaces = connections.send_command(
            "display interface brief", delay_factor=2, timeout=5, read_timeout=15
        )
        up_interface = 0
        down_interface = 0
        for line in output_interfaces.split("\n"):
            if "UP" in line and "DOWN" not in line:
                up_interface += 1
            elif "DOWN" in line:
                down_interface += 1
        total_interface = up_interface + down_interface
        return total_interface, up_interface, down_interface, error_massage
    except Exception as e:
        logger.error(f"错误：【子功能】检查接口状态出错 {e}")
        error_massage = "检查端口状态失败"
        return 0, 0, 0, error_massage


# 第三步：检查CPU使用率
def check_cpu_usage(connections):
    error_massage = ""
    try:
        output_cpu_usage = connections.send_command("display cpu-usage", delay_factor=2, timeout=5, read_timeout=15)
        for line in output_cpu_usage.split("\n"):
            if "seconds" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    return f"{match.group(1)}%", error_massage
                else:
                    logger.error("并未查询到CPU使用率！")
                    return "N/A", error_massage
        return "N/A", error_massage
    except Exception as e:
        logger.error(f"错误：【子功能】检查CPU使用率出错！ {e}")
        error_massage = "检查CPU使用率失败！"
        return "N/A", error_massage


# 第四步：检查内存使用率
def check_memory_usage(connections):
    error_massage = ""
    try:
        output_memory_usage = connections.send_command(
            "display memory-threshold", delay_factor=2, timeout=5, read_timeout=15
        )
        for line in output_memory_usage.split("\n"):
            if "Memory" in line and "usage" in line:
                match = re.search(r"(\d+)%", line)
                if match:
                    return f"{match.group(1)}%", error_massage
                else:
                    logger.error("并未查询到内存使用率！")
                    return "N/A", error_massage
        return "N/A", error_massage
    except Exception as e:
        logger.error(f"错误：【子功能】检查内存使用率出错！ {e}")
        error_massage = "检查内存使用率失败"
        return "N/A", error_massage


# 第五步对单个设备进行检查
def check_single_device(device_info):
    logger.info(f"正在连接设备{device_info['host']}......")
    connections = None
    results = {
        "host": device_info["host"],
        "status": "未知",
        "up_interface": 0,
        "down_interface": 0,
        "total_interface": 0,
        "CPU_usage": "N/A",
        "memory_usage": "N/A",
        "error_message": "",
    }
    try:
        connections = ConnectHandler(**device_info)
        logger.info("连接成功！")
        logger.info(f"正在检查设备{device_info['host']}的各项状态.......")
        try:
            total_interface, up_interface, down_interface, if_error = check_interface_status(connections)
            if if_error:
                results["error_message"] += "检查端口状态失败"
        except Exception as e:
            results["error_message"] += f"检查端口状态失败 {e}"
            total_interface, up_interface, down_interface = 0, 0, 0
        try:
            CPU_usage, if_error = check_cpu_usage(connections)
            if if_error:
                results["error_message"] += "检查CPU使用率失败！"
        except Exception as e:
            results["error_message"] += f"检查CPU使用率失败！ {e}"
            CPU_usage = "N/A"
        try:
            memory_usage, if_error = check_memory_usage(connections)
            if if_error:
                results["error_message"] += "检查内存使用率失败！"
        except Exception as e:
            results["error_message"] += f"检查内存使用率失败！ {e}"
            memory_usage = "N/A"
        results.update(
            {
                "status": "成功",
                "up_interface": up_interface,
                "down_interface": down_interface,
                "total_interface": total_interface,
                "CPU_usage": CPU_usage,
                "memory_usage": memory_usage,
            }
        )
        logger.info("检查成功！")
        logger.info(f"-设备：{results['host']}")
        logger.info(f"-活跃端口（UP）数量：{results['up_interface']}")
        logger.info(f"-活跃端口（UP）数量/设备总接口数：{results['up_interface']}/{results['total_interface']}")
        logger.info(f"-CPU使用率：{results['CPU_usage']}")
        logger.info(f"-内存使用率：{results['memory_usage']}")
        if results["down_interface"] > 0:
            logger.warning(f"-端口存在异常：{results['down_interface']}个DOWN端口！")
        if results["error_message"]:
            logger.warning(f"-错误信息：{results['error_message']}")
        logger.info("检查完毕！")
        return results
    except Exception as e:
        error_msg = str(e)
        logger.error("连接失败！")
        if "Authentication" in error_msg:
            logger.error(f"   原因：认证失败！请检查用户名/密码！")
        elif "Timeout" in error_msg:
            logger.error(f"   原因：连接超时，设备可能不可达或防火墙阻断！")
        elif "DNS failure" in error_msg:
            logger.error(f"   原因：无法解析主机名！请检查IP地址")
        else:
            logger.error(f"   原因：{e[:50]}......")
        results.update({"status": "失败", "error_message": error_msg[:100]})
        return results
    finally:
        if connections:
            try:
                connections.disconnect()
            except:
                pass


# 第六步：写检查报告
def write_health_report(results, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("-------网络设备检查报告-------\n")
            f.write("=" * 60)
            for res in results:
                host = res.get("host", "未知")
                up = res.get("up_interface", 0)
                down = res.get("down_interface", 0)
                total = res.get("total_interface", 0)
                cpu = res.get("CPU_usage", "N/A")
                memory = res.get("memory_usage", "N/A")
                error_msg = res.get("error_message", "未知")
                f.write(f"\n-设备：{host}\n")
                f.write(f"-活跃端口（UP）数量：{up}\n")
                f.write(f"-活跃端口（UP）数量/设备总接口数：{up}/{total}\n")
                f.write(f"-CPU使用率：{cpu}\n")
                f.write(f"-内存使用率：{memory}\n")
                if down > 0:
                    f.write(f"-端口存在异常：{down}个DOWN端口！\n")
                if error_msg:
                    f.write(f"-错误信息：{error_msg}\n")
    except Exception as e:
        logger.error(f"写检查报告时出现严重错误：{e}")


# 第七步：写主函数
def main():
    logger.info("----网络设备检查脚本（支持多个设备同时检查）----\n")
    logger.info("=" * 60)
    devices = read_devices_yml()  # 文件名需自己填！
    if not devices:
        logger.error("未读取任何设备！请查看出错原因！")
        return
    parse = argparse.ArgumentParser(description="网络设备自动检查脚本")
    parse.add_argument("--all", action="store_true", help="模式：检查所有已经读的取设备")
    parse.add_argument("--ip", type=str, nargs="+", help="模式：指定一个或者多个设备检查")
    args = parse.parse_args()
    target_devices = []
    if args.all:
        logger.info(f"模式：检查已经读取的所有设备！ 共{len(devices)}台设备")
        target_devices = devices
    elif args.ip:
        logger.info(f"模式：指定一个设备或者多个设备开始进行检查")
        for ip in args.ip:
            match = [d for d in devices if d["host"] == ip]
            if match:
                logger.info(f"已经将{ip}加入到检查列表当中！")
                target_devices.extend(match)
            else:
                logger.warning(f"并未查询到此IP，已跳过此IP！")
    else:
        logger.error("请输入有效命令，--help查看帮助")
        parse.print_help()
    device_results = []
    success = 0
    total_down_interface = 0
    for device in target_devices:
        logger.info(f"正在准备检查设备:{device['host']}.......")
        device_result = check_single_device(device)
        if device_result["status"] == "成功":
            success += 1
            total_down_interface += device_result["down_interface"]
        device_results.append(device_result)
    logger.info("检查设备健康完毕！")
    logger.info("=" * 60)
    logger.info(f"\n成功检查设备/已经读取的设备：{success}/{len(devices)}")
    logger.info(f"总共的DOWN接口数：{total_down_interface}")
    logger.info("\n记得查看备份之后的文件哦！")
    write_health_report(device_results, "health_check_report.txt")
    logger.info(f"检查报告书写完毕！名称：health_check_report.txt")


if __name__ == "__main__":
    main()
