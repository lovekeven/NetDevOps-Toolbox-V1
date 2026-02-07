import os
import argparse
import re
from netmiko import ConnectHandler
import yaml
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
CONFIG_PATH = os.path.join(ROOT_DIR, "config", "devices.yaml")
from utils.log_setup import setup_logger

logger = setup_logger("netdevops_health_check", "health_check.log")
from datetime import datetime
from utils.models import get_global_physical_cards

# 引入数据库
from db.database import db_manager


# 第一步：定义可以读取yml文件的函数
def read_devices_yml(filename=CONFIG_PATH, yaml_connect=None):
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
        output_interfaces = connections.send_command("display interface brief", delay_factor=2)
        # 1.send_command() 不支持 timeout 和 read_timeout 参数，传递后触发报错，跟那个device_name一样
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
        output_cpu_usage = connections.send_command("display cpu-usage", delay_factor=2)
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
        output_memory_usage = connections.send_command("display memory-threshold", delay_factor=2)
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


# 补充检查设备版本信息
def check_device_version(connections):
    error_massage = ""
    try:
        version_result = connections.send_command("display version", delay_factor=2)
        if not version_result:
            return "未知", error_massage
        else:
            return version_result[:100], error_massage
    except Exception as e:
        logger.error(f"错误：【子功能】检查版本信息出错！ {e}")
        error_massage = "检查版本信息失败"
        return "未知", error_massage


# 第五步对单个设备进行检查（改造后：绑定全局卡片+统一样式，对齐并发框架）
def check_single_device(device_info):
    # 新增1：定义适配函数（放在函数最上方，成功/失败分支均可调用）
    def adapt_db_data(original_result):
        """健康检查结果适配：列表→字符串，布尔→文本，适配数据库TEXT/INTEGER字段"""
        adapted_result = original_result.copy()
        # 1. 健康问题列表→分号分隔字符串（适配device_health_issues TEXT字段）
        if isinstance(adapted_result.get("device_health_issues"), list):
            adapted_result["device_health_issues"] = ";".join(adapted_result["device_health_issues"])
        if not adapted_result.get("device_health_issues"):
            adapted_result["device_health_issues"] = "无"
        # 2. 可达性布尔→文本（适配reachable TEXT字段：可达/不可达）
        if isinstance(adapted_result.get("reachable"), bool):
            adapted_result["reachable"] = "可达" if adapted_result["reachable"] else "不可达"
        # 3. 数字字段兜底（防止传非int，适配up/down/total_interface INTEGER字段）
        for key in ["up_interface", "down_interface", "total_interface"]:
            if adapted_result.get(key) is not None:
                try:
                    adapted_result[key] = int(adapted_result[key])
                except (ValueError, TypeError):
                    adapted_result[key] = 0
        return adapted_result

    logger.info(f"正在连接设备{device_info['host']}......")
    connections = None
    # 1. 初始化结果字典：补check_time（并发框架必带），字段和并发完全对齐，保留你的原有字段
    results = {
        "host": device_info["host"],
        "device_name": "未知设备",  # 从全局卡片拉取，统一设备名字段
        "version": "未知",
        "status": "unknown",  # 设备健康状态：healthy/degraded/failed，这个具体看你的cpu,内存使用率了过高就报警么
        "check_status": "成功",  # 检查流程状态（成功/失败）,就是看你检查成功还是失败了
        "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 统一时间戳，并发框架通用
        "up_interface": 0,
        "down_interface": 0,
        "total_interface": 0,
        "CPU_usage": "N/A",
        "memory_usage": "N/A",
        "device_health_issues": [],
        "error_message": "",
        "reachable": True,
    }
    # 2. 核心：绑定全局设备卡片，从卡片拉取设备名（和并发框架的设备档案统一）
    try:
        physical_cards = get_global_physical_cards()  # 调用全局变量，获取所有设备卡片，这里得到的是列表，元素是对象
        # 根据IP匹配当前设备的卡片，next避免遍历，效率高
        current_card = next((card for card in physical_cards if card.ip_address == device_info["host"]), None)
        if current_card:
            results["device_name"] = current_card.name  # 替换为卡片里的设备名
            logger.info(f"设备卡片匹配成功：{results['device_name']}({device_info['host']})")
        else:
            logger.warning(f"未匹配到{device_info['host']}的设备卡片，使用默认设备名")
    except Exception as e:
        logger.error(f"加载全局设备卡片失败：{e}")
        results["error_message"] += f"设备卡片加载失败；"

    try:
        # 3. 原有连接逻辑不变，成功后更新status为"成功"
        connections = ConnectHandler(**device_info)
        logger.info("连接成功！")
        logger.info(f"正在检查设备{results['device_name']}({device_info['host']})的各项状态.......")

        # 4. 原有接口检查逻辑不变，直接复用
        try:
            total_interface, up_interface, down_interface, if_error = check_interface_status(connections)
            if if_error:
                results["error_message"] += "检查端口状态失败；"
        except Exception as e:
            results["error_message"] += f"检查端口状态失败 {e}；"
            total_interface, up_interface, down_interface = 0, 0, 0

        try:
            CPU_usage, if_error = check_cpu_usage(connections)
            if if_error:
                results["error_message"] += "检查CPU使用率失败！；"
        except Exception as e:
            results["error_message"] += f"检查CPU使用率失败！ {e}；"
            CPU_usage = "N/A"

        try:
            memory_usage, if_error = check_memory_usage(connections)
            if if_error:
                results["error_message"] += "检查内存使用率失败！；"
        except Exception as e:
            results["error_message"] += f"检查内存使用率失败！ {e}；"
            memory_usage = "N/A"
        try:
            version_result, if_error = check_device_version(connections)
            if if_error:
                results["error_message"] += "检查设备版本信息失败！；"
        except Exception as e:
            results["error_message"] += f"检查设备版本信息失败！ {e}；"
            version_result = "未知"
        device_health_issues = []
        # 1. 关键端口GE1/0/1 DOWN判断（和并发一致）
        # 先从接口结果里判断关键端口状态（单设备需补这段接口解析，下面会给）
        critical_ports_down = False
        # 直接重新获取接口结果，避免变量不存在的问题，和并发解析逻辑完全一致
        try:
            output_interfaces = connections.send_command("display interface brief", delay_factor=2)
            lines = output_interfaces.split("\n")
            for line in lines:
                line_clean = line.strip().upper()
                if line_clean.startswith("GE1/0/1 ") and "DOWN" in line_clean:
                    critical_ports_down = True
                    break
        except Exception as e:
            logger.warning(f"检测关键端口GE1/0/1状态失败：{e}")
        if critical_ports_down:
            device_health_issues.append("关键端口DOWN")
        # 2. 端口DOWN占比超30%判断（和并发一致）
        if results["total_interface"] > 0 and (results["down_interface"] / results["total_interface"]) > 0.3:
            device_health_issues.append(f"过多端口down ({results['down_interface']}/{results['total_interface']})")
        # 3. CPU使用率超88%判断（和并发一致）
        if results["CPU_usage"] != "N/A":
            cpu_num = int(results["CPU_usage"].replace("%", ""))
            # 把字符串里的百分号%全部替换成空字符串
            if cpu_num > 88:
                device_health_issues.append("CPU使用率过高，已经超过88%")
        # 4. 内存使用率超88%判断（和并发一致）
        if results["memory_usage"] != "N/A":
            mem_num = int(results["memory_usage"].replace("%", ""))
            if mem_num > 88:
                device_health_issues.append("内存使用率过高，已经超过88%")
        # 列表空时设为["无"]（和并发一致），保证前端展示统一
        device_health_issues = device_health_issues if device_health_issues else ["无"]

        # 7. 更新检查结果，保留原有逻辑
        results.update(
            {
                "check_status": "成功",  # 检查流程成功，显式标记
                "status": (
                    "healthy" if device_health_issues == ["无"] else "degraded"
                ),  # 核心：根据问题列表判断设备健康状态
                "up_interface": up_interface,
                "down_interface": down_interface,
                "total_interface": total_interface,
                "CPU_usage": CPU_usage,
                "memory_usage": memory_usage,
                "version": version_result,
                "device_health_issues": device_health_issues,  # 补更：健康问题列表
                # "error_message": (
                #     results["error_message"] + ";" + ";".join(device_health_issues)
                #     if device_health_issues != ["无"]
                #     else results["error_message"]
                # 补更：从列表拼接错误信息，和并发一致
            }
        )
        # 检查结果插入数据库
        results = adapt_db_data(results)
        db_manager.log_check_device(results)
        if current_card:  # 只有匹配到卡片才更新
            current_card.update(results)
            logger.info(f"已经成功更新{current_card.name}({current_card.ip_address}的档案卡片！)")
        else:
            logger.warning(f"并未匹配到设备{results['device_name']}({device_info['host']}的档案卡片，无法更新)")
            # 这个函数不可以传设备名字的参数，这里肯定是未知设备

        logger.info("检查成功！")
        logger.info(f"-设备：{results['device_name']}（{results['host']}）")
        logger.info(f"-版本：{results['version']}")
        logger.info(f"-活跃端口（UP）数量：{results['up_interface']}")
        logger.info(f"-活跃端口（UP）数量/设备总接口数：{results['up_interface']}/{results['total_interface']}")
        logger.info(f"-CPU使用率：{results['CPU_usage']}")
        logger.info(f"-内存使用率：{results['memory_usage']}")
        logger.info(f"-设备健康状态：{results['status']} | 存在问题：{results['device_health_issues']}")
        if results["down_interface"] > 0:
            logger.warning(f"-端口存在异常：{results['down_interface']}个DOWN端口！")
        if results["error_message"]:
            logger.warning(f"-错误信息：{results['error_message']}")
        logger.info("检查完毕！")
        return results
    except Exception as e:
        error_msg = str(e)
        logger.error(f"设备{results['device_name']}（{device_info['host']}）连接失败！")
        try:
            if "authentication" in error_msg.lower() or "Authentication" in error_msg:
                err_detail = "认证失败！请检查用户名/密码！"
            elif "timeout" in error_msg.lower() or "Timeout" in error_msg:
                err_detail = "连接超时，设备可能不可达或防火墙阻断！"
            elif "dns" in error_msg.lower() or "DNS" in error_msg:
                err_detail = "无法解析主机名！请检查IP地址！"
            else:
                err_detail = f"{error_msg[:50]}......"
            # 打印失败原因（现在能正常打印了）
            logger.error(f"   失败原因：{err_detail}")
        except Exception as sub_e:
            # 就算判断失败，也给默认原因，不中断后续逻辑
            err_detail = f"连接失败，原因解析异常：{str(sub_e)[:30]}......"
            logger.error(f"   失败原因（解析异常）：{err_detail}")

        results.update(
            {
                "status": "failed",  # 检查流程失败，设备健康状态标为failed
                "check_status": "失败",  # 检查流程状态标为失败
                "reachable": False,  # 连不上设备，可达性标为False
                "device_health_issues": ["无"],  # 没检查成，无健康问题
                "error_message": err_detail,
            }
        )
        logger.error("准备执行健康检查失败记录入库...")
        results = adapt_db_data(results)
        db_manager.log_check_device(results)
        logger.error("健康检查失败记录入库执行完成，准备更新卡片...")
        if current_card:  # 只有匹配到卡片才更新
            current_card.update(results)
            logger.info(f"已经更新{current_card.name}的健康档案卡片")
        return results

    finally:
        if connections:
            try:
                connections.disconnect()
                logger.info(f"设备{device_info['host']}连接已正常断开")
            except Exception as e:
                logger.warning(f"设备{device_info['host']}连接断开失败：{e}")
                pass


# # 第五步对单个设备进行检查
# def check_single_device(device_info):
#     logger.info(f"正在连接设备{device_info['host']}......")
#     connections = None
#     results = {
#         "host": device_info["host"],
#         "status": "未知",
#         "up_interface": 0,
#         "down_interface": 0,
#         "total_interface": 0,
#         "CPU_usage": "N/A",
#         "memory_usage": "N/A",
#         "error_message": "",
#     }
#     try:
#         connections = ConnectHandler(**device_info)
#         logger.info("连接成功！")
#         logger.info(f"正在检查设备{device_info['host']}的各项状态.......")
#         try:
#             total_interface, up_interface, down_interface, if_error = check_interface_status(connections)
#             if if_error:
#                 results["error_message"] += "检查端口状态失败"
#         except Exception as e:
#             results["error_message"] += f"检查端口状态失败 {e}"
#             total_interface, up_interface, down_interface = 0, 0, 0
#         try:
#             CPU_usage, if_error = check_cpu_usage(connections)
#             if if_error:
#                 results["error_message"] += "检查CPU使用率失败！"
#         except Exception as e:
#             results["error_message"] += f"检查CPU使用率失败！ {e}"
#             CPU_usage = "N/A"
#         try:
#             memory_usage, if_error = check_memory_usage(connections)
#             if if_error:
#                 results["error_message"] += "检查内存使用率失败！"
#         except Exception as e:
#             results["error_message"] += f"检查内存使用率失败！ {e}"
#             memory_usage = "N/A"
#         results.update(
#             {
#                 "status": "成功",
#                 "up_interface": up_interface,
#                 "down_interface": down_interface,
#                 "total_interface": total_interface,
#                 "CPU_usage": CPU_usage,
#                 "memory_usage": memory_usage,
#             }
#         )
#         logger.info("检查成功！")
#         logger.info(f"-设备：{results['host']}")
#         logger.info(f"-活跃端口（UP）数量：{results['up_interface']}")
#         logger.info(f"-活跃端口（UP）数量/设备总接口数：{results['up_interface']}/{results['total_interface']}")
#         logger.info(f"-CPU使用率：{results['CPU_usage']}")
#         logger.info(f"-内存使用率：{results['memory_usage']}")
#         if results["down_interface"] > 0:
#             logger.warning(f"-端口存在异常：{results['down_interface']}个DOWN端口！")
#         if results["error_message"]:
#             logger.warning(f"-错误信息：{results['error_message']}")
#         logger.info("检查完毕！")
#         return results
#     except Exception as e:
#         error_msg = str(e)
#         logger.error("连接失败！")
#         if "Authentication" in error_msg:
#             logger.error(f"   原因：认证失败！请检查用户名/密码！")
#         elif "Timeout" in error_msg:
#             logger.error(f"   原因：连接超时，设备可能不可达或防火墙阻断！")
#         elif "DNS failure" in error_msg:
#             logger.error(f"   原因：无法解析主机名！请检查IP地址")
#         else:
#             logger.error(f"   原因：{e[:50]}......")
#         results.update({"status": "失败", "error_message": error_msg[:100]})
#         return results
#     finally:
#         if connections:
#             try:
#                 connections.disconnect()
#             except:
#                 pass


# 第六步：写检查报告
def write_health_report(results, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("-------网络设备检查报告-------\n")
            f.write("=" * 60)
            for res in results:
                host = res.get("host", "未知")
                version = res.get("version", "未知")
                up = res.get("up_interface", 0)
                down = res.get("down_interface", 0)
                total = res.get("total_interface", 0)
                cpu = res.get("CPU_usage", "N/A")
                memory = res.get("memory_usage", "N/A")
                error_msg = res.get("error_message", "未知")
                f.write(f"\n-设备：{host}\n")
                f.write(f"-版本：{version}\n")
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
