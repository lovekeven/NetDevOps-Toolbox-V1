import time
import os
import argparse
from netmiko import ConnectHandler
import yaml
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
BACKUP_DIR = os.path.join(
    ROOT_DIR,
)
from utils.log_setup import setup_logger
from utils.retry_decorator import ssh_retry


CONFIG_PATH = os.path.join(ROOT_DIR, "config", "devices.yaml")
logger = setup_logger("netdevops_backup", "backup.log")


# 第一步创建一个可以读取yaml文件的自定义函数
def read_devices_yml(filename):
    device_list = []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            for device_name, device_info in data["devices"].items():
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
    except FileNotFoundError:
        logger.critical("错误：未找到对应文件！")
        return device_list
    except KeyError as e:
        logger.critical(f"错误：相应文件内键值存在问题  {e}")
        return device_list
    except yaml.YAMLError as e:
        logger.critical(f"错误：未成功解析相应的文件！ {e}")
        return device_list


# 第二步：对单个设备进行备份
@ssh_retry
def backup_single_device(device_info):
    logger.info(f"正在尝试连接{device_info['host']}......")
    connections = None
    try:
        connections = ConnectHandler(**device_info)
        logger.info("连接成功！")
        logger.info(f"正在开始备份设备{device_info['host']}........请稍后....")
        output = connections.send_command("display interface brief")  # 这里以备份接口信息为例
        backup_dir = os.path.join(ROOT_DIR, "backupN1")  # "backupN1"  # N1的意思是创建第一个文件夹，以后若有需要可以该
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = os.path.join(backup_dir, f"{device_info['host']}__配置__{timestamp}.txt")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(output)
        logger.info(f"设备{device_info['host']}备份成功！")
        logger.info(f"备份之后的路径\文件名为：{filename}")
        return True
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
            logger.error(f"   原因：{error_msg[:50]}......")
        raise  # 这里不可以反回FLase，因为如果返回的话，在装饰器里面是判定该语句执行成功，这样就不会触发重试机制
    # 谁调用它，他就把错误抛给谁，现在他把错误抛给了装饰器，而且装饰器也有raise，装饰器把异常抛给了，调用装饰器的主函数
    finally:
        if connections:
            try:
                connections.disconnect()
            except:
                pass


# 第三步：写主函数并且调用其他函数
def main():
    logger.info("网络设备自动备份脚本（支持多个设备同时备份）\n")
    logger.info("=" * 60)
    devices = read_devices_yml(CONFIG_PATH)  # 文件名需自己填！
    if not devices:
        logger.error("未读取任何设备！请查看出错原因！")
        return
    parse = argparse.ArgumentParser(description="网络设备自动备份脚本")
    parse.add_argument("--all", action="store_true", help="模式：备份所有已经读的取设备")
    parse.add_argument("--ip", type=str, nargs="+", help="模式：指定一个或者多个设备备份")
    args = parse.parse_args()
    target_devices = []
    if args.all:
        logger.info(f"模式：备份已经读取的所有设备！ 共{len(devices)}台设备")
        target_devices = devices
    elif args.ip:
        logger.info(f"模式：指定一个设备或者多个设备开始备份")
        for ip in args.ip:
            match = [d for d in devices if d["host"] == ip]
            if match:
                logger.info(f"已经将{ip}加入到备份列表当中！")
                target_devices.extend(match)
            else:
                logger.info(f"并未查询到此IP，已跳过此IP！")
    else:
        logger.info("请输入有效命令，--help查看帮助")
        parse.print_help()
    success = 0
    for device in target_devices:
        logger.info(f"正在准备备份设备{device['host']}......")
        try:
            if backup_single_device(device):
                success += 1
        except Exception as e:  # 他最后收到别人抛出来的异常！优雅的解决异常！
            logger.warning(f"设备{device['host']} 重试耗尽后仍连接失败，跳过该设备")
    logger.info("=" * 60)
    logger.info(f"\n成功备份设备/已经读取的设备：{success}/{len(devices)}")
    logger.info("\n记得查看备份之后的文件哦！")


if __name__ == "__main__":
    main()
