"""
优化版健康检查模块
支持真实设备和模拟器双模式，提升检查速度和准确性
"""

import os
import re
import yaml
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from utils.log_setup import setup_logger
from utils.models import get_global_physical_cards
from db.database import db_manager

logger = setup_logger("netdevops_health_check", "health_check.log")

# ============================================================
# 配置常量
# ============================================================

# 检查模式
CHECK_MODE_REAL = "real"      # 真实设备模式
CHECK_MODE_SIMULATOR = "sim"  # 模拟器模式

# 超时配置（秒）
TIMEOUT_CONFIG = {
    CHECK_MODE_REAL: {
        "connection": 10,
        "command": 30,
        "global_delay_factor": 1,
    },
    CHECK_MODE_SIMULATOR: {
        "connection": 5,
        "command": 10,
        "global_delay_factor": 2,
    }
}

# 温度告警阈值（摄氏度）
TEMP_WARNING_THRESHOLD = 60
TEMP_DANGER_THRESHOLD = 80

# 关键端口列表（可配置）
CRITICAL_PORTS = ["GE1/0/1", "GE1/0/2", "GigabitEthernet0/0/1"]

# ============================================================
# 多厂商命令映射
# ============================================================

VENDOR_COMMANDS = {
    "h3c": {
        "interface": "display interface brief",
        "cpu": "display cpu-usage",
        "memory": "display memory",
        "version": "display version",
        "routing": "display ip routing-table",
        "arp": "display arp",
        "mac": "display mac-address",
        "vlan": "display vlan brief",
        "ospf": "display ospf peer brief",
        "bgp": "display bgp peer",
        "environment": "display environment",
        "power": "display power",
        "fan": "display fan",
        "stp": "display stp brief",
        "link_agg": "display link-aggregation summary",
        "config": "display current-configuration",
    },
    "cisco": {
        "interface": "show ip interface brief",
        "cpu": "show processes cpu",
        "memory": "show memory",
        "version": "show version",
        "routing": "show ip route",
        "arp": "show arp",
        "mac": "show mac address-table",
        "vlan": "show vlan brief",
        "ospf": "show ip ospf neighbor",
        "bgp": "show ip bgp summary",
        "environment": "show environment all",
        "power": "show power",
        "fan": "show fans",
        "stp": "show spanning-tree",
        "link_agg": "show etherchannel summary",
        "config": "show running-config",
    },
    "huawei": {
        "interface": "display interface brief",
        "cpu": "display cpu-usage",
        "memory": "display memory",
        "version": "display version",
        "routing": "display ip routing-table",
        "arp": "display arp",
        "mac": "display mac-address",
        "vlan": "display vlan brief",
        "ospf": "display ospf peer brief",
        "bgp": "display bgp peer",
        "environment": "display environment",
        "power": "display power",
        "fan": "display fan",
        "stp": "display stp brief",
        "link_agg": "display link-aggregation summary",
        "config": "display current-configuration",
    },
    "default": {
        "interface": "display interface brief",
        "cpu": "display cpu-usage",
        "memory": "display memory",
        "version": "display version",
        "routing": "display ip routing-table",
        "arp": "display arp",
        "mac": "display mac-address",
        "vlan": "display vlan brief",
        "ospf": "display ospf peer brief",
        "bgp": "display bgp peer",
        "environment": "display environment",
        "power": "display power",
        "fan": "display fan",
        "stp": "display stp brief",
        "link_agg": "display link-aggregation summary",
        "config": "display current-configuration",
    },
}


def get_vendor_command(vendor: str, command_type: str) -> str:
    """
    根据厂商类型获取对应命令

    Args:
        vendor: 厂商类型 (h3c/cisco/huawei)
        command_type: 命令类型 (interface/cpu/memory/...)

    Returns:
        对应的CLI命令
    """
    vendor = vendor.lower() if vendor else "default"
    return VENDOR_COMMANDS.get(vendor, VENDOR_COMMANDS["default"]).get(command_type, "")


# ============================================================
# 设备连接管理
# ============================================================

class DeviceConnection:
    """设备连接管理器"""

    def __init__(self, device_info: Dict, mode: str = CHECK_MODE_REAL):
        """
        初始化设备连接

        Args:
            device_info: 设备信息字典
            mode: 检查模式 (real/sim)
        """
        self.device_info = device_info
        self.mode = mode
        self.connection = None
        self.timeout_config = TIMEOUT_CONFIG[mode]

    def connect(self) -> bool:
        """
        建立设备连接

        Returns:
            连接是否成功
        """
        try:
            from netmiko import ConnectHandler

            # 准备连接参数
            device_params = {
                "device_type": self.device_info.get("device_type", "huawei_telnet"),
                "host": self.device_info.get("host", ""),
                "port": self.device_info.get("port", 22),
                "username": self.device_info.get("username", ""),
                "password": self.device_info.get("password", ""),
                "timeout": self.timeout_config["connection"],
                "global_delay_factor": self.timeout_config["global_delay_factor"],
                "fast_cli": False,
            }

            # 建立连接
            self.connection = ConnectHandler(**device_params)
            logger.info(f"成功连接到设备: {self.device_info.get('host')}")
            return True

        except Exception as e:
            logger.error(f"连接设备失败: {self.device_info.get('host')} - {str(e)}")
            return False

    def disconnect(self):
        """断开设备连接"""
        if self.connection:
            try:
                self.connection.disconnect()
                logger.info(f"已断开设备连接: {self.device_info.get('host')}")
            except Exception as e:
                logger.warning(f"断开连接时出错: {str(e)}")

    def execute_command(self, command: str) -> Tuple[bool, str]:
        """
        执行设备命令

        Args:
            command: 要执行的命令

        Returns:
            (是否成功, 命令输出)
        """
        if not self.connection:
            return False, "未建立连接"

        try:
            output = self.connection.send_command_timing(
                command,
                delay_factor=self.timeout_config["global_delay_factor"],
                max_loops=100
            )
            return True, output

        except Exception as e:
            logger.error(f"执行命令失败: {command} - {str(e)}")
            return False, str(e)


# ============================================================
# 健康检查函数
# ============================================================

def check_interface_status(connection: DeviceConnection, vendor: str = None) -> Dict:
    """
    检查接口状态

    Args:
        connection: 设备连接
        vendor: 厂商类型

    Returns:
        接口状态字典
    """
    command = get_vendor_command(vendor, "interface")
    success, output = connection.execute_command(command)

    if not success:
        return {"status": "error", "message": "获取接口状态失败", "interfaces": []}

    # 解析接口状态
    interfaces = []
    up_count = 0
    down_count = 0

    lines = output.split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("Interface") or line.startswith("-"):
            continue

        # 解析接口行（适配不同厂商格式）
        parts = line.split()
        if len(parts) >= 4:
            iface_name = parts[0]
            ip_addr = parts[1] if len(parts) > 1 else ""
            status = parts[-1] if len(parts) > 2 else ""

            # 判断接口状态
            is_up = "UP" in status.upper() and "DOWN" not in status.upper()
            if is_up:
                up_count += 1
            else:
                down_count += 1

            interfaces.append({
                "name": iface_name,
                "ip": ip_addr,
                "status": "up" if is_up else "down",
                "raw": line
            })

    return {
        "status": "success",
        "total": len(interfaces),
        "up": up_count,
        "down": down_count,
        "interfaces": interfaces
    }


def check_cpu_usage(connection: DeviceConnection, vendor: str = None) -> Dict:
    """
    检查CPU使用率

    Args:
        connection: 设备连接
        vendor: 厂商类型

    Returns:
        CPU使用率字典
    """
    command = get_vendor_command(vendor, "cpu")
    success, output = connection.execute_command(command)

    if not success:
        return {"status": "error", "message": "获取CPU使用率失败", "usage": 0}

    # 解析CPU使用率
    usage = 0
    try:
        # H3C/华为格式: "CPU Usage: 23%"
        match = re.search(r"CPU\s*Usage:\s*(\d+)%", output, re.IGNORECASE)
        if match:
            usage = int(match.group(1))
        else:
            # Cisco格式: "CPU utilization for five seconds: 23%"
            match = re.search(r"five seconds:\s*(\d+)%", output, re.IGNORECASE)
            if match:
                usage = int(match.group(1))
            else:
                # 通用格式: 查找百分比数字
                match = re.search(r"(\d+)%", output)
                if match:
                    usage = int(match.group(1))
    except Exception as e:
        logger.warning(f"解析CPU使用率失败: {str(e)}")

    return {
        "status": "success",
        "usage": usage,
        "raw": output[:200]  # 只保留前200字符
    }


def check_memory_usage(connection: DeviceConnection, vendor: str = None) -> Dict:
    """
    检查内存使用率

    Args:
        connection: 设备连接
        vendor: 厂商类型

    Returns:
        内存使用率字典
    """
    command = get_vendor_command(vendor, "memory")
    success, output = connection.execute_command(command)

    if not success:
        return {"status": "error", "message": "获取内存使用率失败", "usage": 0}

    # 解析内存使用率
    usage = 0
    try:
        # 查找 "Used: 123456 bytes (45%)" 格式
        match = re.search(r"Used:\s*\d+\s*bytes\s*\((\d+)%\)", output, re.IGNORECASE)
        if match:
            usage = int(match.group(1))
        else:
            # 查找 "Memory Usage: 45%" 格式
            match = re.search(r"Memory\s*Usage:\s*(\d+)%", output, re.IGNORECASE)
            if match:
                usage = int(match.group(1))
            else:
                # 通用格式: 查找百分比数字
                match = re.search(r"(\d+)%", output)
                if match:
                    usage = int(match.group(1))
    except Exception as e:
        logger.warning(f"解析内存使用率失败: {str(e)}")

    return {
        "status": "success",
        "usage": usage,
        "raw": output[:200]
    }


def check_device_version(connection: DeviceConnection, vendor: str = None) -> Dict:
    """
    检查设备版本

    Args:
        connection: 设备连接
        vendor: 厂商类型

    Returns:
        设备版本字典
    """
    command = get_vendor_command(vendor, "version")
    success, output = connection.execute_command(command)

    if not success:
        return {"status": "error", "message": "获取设备版本失败", "version": "未知"}

    # 解析版本信息
    version = "未知"
    try:
        # H3C/华为格式: "Version 7.1.075"
        match = re.search(r"Version\s+([\d.]+)", output, re.IGNORECASE)
        if match:
            version = match.group(1)
        else:
            # Cisco格式: "Cisco IOS Software, Version 15.2(4)M"
            match = re.search(r"Version\s+([\d.()]+)", output, re.IGNORECASE)
            if match:
                version = match.group(1)
            else:
                # 通用格式: 查找版本号
                match = re.search(r"v?(\d+\.\d+\.\d+)", output, re.IGNORECASE)
                if match:
                    version = match.group(1)
    except Exception as e:
        logger.warning(f"解析设备版本失败: {str(e)}")

    return {
        "status": "success",
        "version": version,
        "raw": output[:200]
    }


def check_routing_table(connection: DeviceConnection, vendor: str = None) -> Dict:
    """
    检查路由表

    Args:
        connection: 设备连接
        vendor: 厂商类型

    Returns:
        路由表字典
    """
    command = get_vendor_command(vendor, "routing")
    success, output = connection.execute_command(command)

    if not success:
        return {"status": "error", "message": "获取路由表失败", "route_count": 0}

    # 统计路由数量
    route_count = 0
    routes = []

    lines = output.split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("Destination") or line.startswith("-") or line.startswith("Total"):
            continue

        # 判断是否为路由条目
        if "/" in line or "Static" in line or "O " in line or "S " in line:
            route_count += 1
            if len(routes) < 5:  # 只保留前5条示例
                routes.append(line[:100])

    return {
        "status": "success",
        "route_count": route_count,
        "routes": routes,
        "raw": output[:500]
    }


def check_arp_table(connection: DeviceConnection, vendor: str = None) -> Dict:
    """
    检查ARP表

    Args:
        connection: 设备连接
        vendor: 厂商类型

    Returns:
        ARP表字典
    """
    command = get_vendor_command(vendor, "arp")
    success, output = connection.execute_command(command)

    if not success:
        return {"status": "error", "message": "获取ARP表失败", "arp_count": 0}

    # 统计ARP条目数量
    arp_count = 0
    entries = []

    lines = output.split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("IP Address") or line.startswith("-") or line.startswith("Total"):
            continue

        # 判断是否为ARP条目（包含IP和MAC地址）
        if ":" in line or "-" in line:
            arp_count += 1
            if len(entries) < 5:
                entries.append(line[:100])

    return {
        "status": "success",
        "arp_count": arp_count,
        "entries": entries,
        "raw": output[:500]
    }


def check_environment_info(connection: DeviceConnection, vendor: str = None) -> Dict:
    """
    检查环境信息（温度、电源、风扇）

    Args:
        connection: 设备连接
        vendor: 厂商类型

    Returns:
        环境信息字典
    """
    result = {
        "temperature": {"status": "unknown", "value": "N/A", "alert": ""},
        "power": {"status": "unknown", "count": 0},
        "fan": {"status": "unknown", "count": 0},
    }

    # 检查温度
    try:
        command = get_vendor_command(vendor, "environment")
        success, output = connection.execute_command(command)

        if success and output:
            # 提取温度值
            temp_match = re.search(r"(\d+)\s*°?[Cc]", output)
            if temp_match:
                temp_value = int(temp_match.group(1))
                result["temperature"]["value"] = f"{temp_value}°C"

                # 温度告警判断
                if temp_value >= TEMP_DANGER_THRESHOLD:
                    result["temperature"]["status"] = "danger"
                    result["temperature"]["alert"] = "温度过高！"
                elif temp_value >= TEMP_WARNING_THRESHOLD:
                    result["temperature"]["status"] = "warning"
                    result["temperature"]["alert"] = "温度偏高"
                else:
                    result["temperature"]["status"] = "normal"
                    result["temperature"]["alert"] = "正常"
    except Exception as e:
        logger.warning(f"检查温度失败: {str(e)}")

    # 检查电源
    try:
        command = get_vendor_command(vendor, "power")
        success, output = connection.execute_command(command)

        if success and output:
            power_count = output.count("Normal") + output.count("正常")
            result["power"]["count"] = power_count
            result["power"]["status"] = "normal" if power_count > 0 else "abnormal"
    except Exception as e:
        logger.warning(f"检查电源失败: {str(e)}")

    # 检查风扇
    try:
        command = get_vendor_command(vendor, "fan")
        success, output = connection.execute_command(command)

        if success and output:
            fan_count = output.count("Normal") + output.count("正常")
            result["fan"]["count"] = fan_count
            result["fan"]["status"] = "normal" if fan_count > 0 else "abnormal"
    except Exception as e:
        logger.warning(f"检查风扇失败: {str(e)}")

    return result


# ============================================================
# 主检查函数
# ============================================================

def check_single_device(device_info: Dict, mode: str = CHECK_MODE_REAL) -> Dict:
    """
    检查单台设备

    Args:
        device_info: 设备信息字典
        mode: 检查模式 (real/sim)

    Returns:
        设备检查结果字典
    """
    start_time = time.time()
    device_name = device_info.get("device_name", "Unknown")
    vendor = device_info.get("vendor", "h3c").lower()

    logger.info(f"开始检查设备: {device_name} (模式: {mode})")

    # 初始化结果
    result = {
        "device_name": device_name,
        "host": device_info.get("host", ""),
        "vendor": vendor,
        "mode": mode,
        "check_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration": 0,
        "status": "success",
        "checks": {}
    }

    # 模拟器模式：返回模拟数据
    if mode == CHECK_MODE_SIMULATOR:
        result["checks"] = _get_simulator_data(device_name, vendor)
        result["duration"] = round(time.time() - start_time, 2)
        logger.info(f"设备 {device_name} 模拟检查完成，耗时: {result['duration']}秒")
        return result

    # 真实设备模式：建立连接并执行检查
    connection = DeviceConnection(device_info, mode)

    try:
        # 建立连接
        if not connection.connect():
            result["status"] = "error"
            result["message"] = "连接失败"
            return result

        # 执行各项检查
        result["checks"]["interface"] = check_interface_status(connection, vendor)
        result["checks"]["cpu"] = check_cpu_usage(connection, vendor)
        result["checks"]["memory"] = check_memory_usage(connection, vendor)
        result["checks"]["version"] = check_device_version(connection, vendor)
        result["checks"]["routing"] = check_routing_table(connection, vendor)
        result["checks"]["arp"] = check_arp_table(connection, vendor)
        result["checks"]["environment"] = check_environment_info(connection, vendor)

        # 更新设备档案卡
        _update_device_profile(device_name, result)

        # 保存到数据库
        _save_to_database(device_name, result)

    except Exception as e:
        logger.error(f"检查设备 {device_name} 时出错: {str(e)}")
        result["status"] = "error"
        result["message"] = str(e)

    finally:
        # 断开连接
        connection.disconnect()

    result["duration"] = round(time.time() - start_time, 2)
    logger.info(f"设备 {device_name} 检查完成，耗时: {result['duration']}秒")

    return result


def _get_simulator_data(device_name: str, vendor: str) -> Dict:
    """
    获取模拟器数据

    Args:
        device_name: 设备名称
        vendor: 厂商类型

    Returns:
        模拟检查数据
    """
    import random

    # 根据设备名称生成不同的模拟数据
    seed = hash(device_name) % 1000
    random.seed(seed)

    return {
        "interface": {
            "status": "success",
            "total": random.randint(4, 24),
            "up": random.randint(3, 20),
            "down": random.randint(0, 4),
            "interfaces": []
        },
        "cpu": {
            "status": "success",
            "usage": random.randint(5, 45),
        },
        "memory": {
            "status": "success",
            "usage": random.randint(30, 70),
        },
        "version": {
            "status": "success",
            "version": f"{random.randint(5, 7)}.{random.randint(0, 9)}.{random.randint(0, 99)}",
        },
        "routing": {
            "status": "success",
            "route_count": random.randint(10, 100),
        },
        "arp": {
            "status": "success",
            "arp_count": random.randint(5, 50),
        },
        "environment": {
            "temperature": {
                "status": random.choice(["normal", "normal", "normal", "warning"]),
                "value": f"{random.randint(35, 55)}°C",
                "alert": "正常"
            },
            "power": {
                "status": "normal",
                "count": random.randint(1, 2)
            },
            "fan": {
                "status": "normal",
                "count": random.randint(2, 4)
            }
        }
    }


def _update_device_profile(device_name: str, result: Dict):
    """
    更新设备档案卡

    Args:
        device_name: 设备名称
        result: 检查结果
    """
    try:
        cards = get_global_physical_cards()
        if device_name in cards:
            card = cards[device_name]
            card["last_check"] = result["check_time"]
            card["status"] = result["status"]

            # 更新各项指标
            if "interface" in result["checks"]:
                card["interface_up"] = result["checks"]["interface"].get("up", 0)
                card["interface_down"] = result["checks"]["interface"].get("down", 0)

            if "cpu" in result["checks"]:
                card["cpu_usage"] = result["checks"]["cpu"].get("usage", 0)

            if "memory" in result["checks"]:
                card["memory_usage"] = result["checks"]["memory"].get("usage", 0)

            if "version" in result["checks"]:
                card["version"] = result["checks"]["version"].get("version", "未知")

    except Exception as e:
        logger.warning(f"更新设备档案卡失败: {str(e)}")


def _save_to_database(device_name: str, result: Dict):
    """
    保存检查结果到数据库

    Args:
        device_name: 设备名称
        result: 检查结果
    """
    try:
        # 保存健康检查记录
        db_manager.save_health_check(
            device_name=device_name,
            status=result["status"],
            cpu_usage=result["checks"].get("cpu", {}).get("usage", 0),
            memory_usage=result["checks"].get("memory", {}).get("usage", 0),
            interface_up=result["checks"].get("interface", {}).get("up", 0),
            interface_down=result["checks"].get("interface", {}).get("down", 0),
            temperature=result["checks"].get("environment", {}).get("temperature", {}).get("value", "N/A"),
            check_time=result["check_time"],
            duration=result["duration"]
        )
    except Exception as e:
        logger.warning(f"保存到数据库失败: {str(e)}")


# ============================================================
# 批量检查函数
# ============================================================

def batch_health_check(devices: List[Dict], mode: str = CHECK_MODE_REAL, max_workers: int = 5) -> List[Dict]:
    """
    批量健康检查

    Args:
        devices: 设备信息列表
        mode: 检查模式
        max_workers: 最大并发数

    Returns:
        检查结果列表
    """
    results = []

    # 使用线程池并发执行
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_device = {
            executor.submit(check_single_device, device, mode): device
            for device in devices
        }

        # 收集结果
        for future in as_completed(future_to_device):
            device = future_to_device[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"检查设备 {device.get('device_name')} 失败: {str(e)}")
                results.append({
                    "device_name": device.get("device_name", "Unknown"),
                    "status": "error",
                    "message": str(e)
                })

    return results


# ============================================================
# 主程序入口
# ============================================================

if __name__ == "__main__":
    # 测试代码
    test_device = {
        "device_name": "SW1",
        "host": "192.168.56.10",
        "port": 22,
        "username": "admin",
        "password": "admin",
        "device_type": "huawei_telnet",
        "vendor": "h3c"
    }

    # 测试模拟器模式
    print("测试模拟器模式...")
    result = check_single_device(test_device, mode=CHECK_MODE_SIMULATOR)
    print(f"结果: {result}")

    # 测试真实设备模式（需要真实设备）
    # print("\n测试真实设备模式...")
    # result = check_single_device(test_device, mode=CHECK_MODE_REAL)
    # print(f"结果: {result}")
