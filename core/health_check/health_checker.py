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

# ============================================================
# 多厂商命令映射（质变级优化 #3）
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


def get_vendor_command(vendor, command_type):
    """
    根据厂商类型获取对应的命令
    :param vendor: 厂商名称（h3c/cisco/huawei）
    :param command_type: 命令类型（interface/cpu/memory/version等）
    :return: 对应厂商的命令字符串
    """
    vendor = vendor.lower() if vendor else "default"
    # 厂商名称映射
    vendor_map = {
        "hclcloud": "h3c",
        "华三h3c": "h3c",
        "h3c": "h3c",
        "cisco": "cisco",
        "华为": "huawei",
        "huawei": "huawei",
    }
    vendor_key = vendor_map.get(vendor, "default")
    commands = VENDOR_COMMANDS.get(vendor_key, VENDOR_COMMANDS["default"])
    return commands.get(command_type, commands.get("interface", "display interface brief"))


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
def check_interface_status(connections, vendor=None):
    error_message = ""
    try:
        # 使用多厂商命令映射
        interface_cmd = get_vendor_command(vendor, "interface")
        output_interfaces = connections.send_command_timing(interface_cmd, delay_factor=2)
        # 1.send_command() 不支持 timeout 和 read_timeout 参数，传递后触发报错，跟那个device_name一样
        up_interface = 0
        down_interface = 0
        for line in output_interfaces.split("\n"):
            if "UP" in line and "DOWN" not in line:
                up_interface += 1
            elif "DOWN" in line:
                down_interface += 1
        total_interface = up_interface + down_interface
        return total_interface, up_interface, down_interface, error_message
    except Exception as e:
        logger.error(f"错误：【子功能】检查接口状态出错 {e}")
        error_message = "检查端口状态失败"
        return 0, 0, 0, error_message


# 第三步：检查CPU使用率
def check_cpu_usage(connections, vendor=None):
    error_message = ""
    try:
        # 使用多厂商命令映射
        cpu_cmd = get_vendor_command(vendor, "cpu")
        # 增加延迟时间，确保命令完成
        output_cpu_usage = connections.send_command_timing(cpu_cmd, delay_factor=5)
        # 添加调试日志
        logger.info(f"CPU输出原始内容: {repr(output_cpu_usage)}")

        # 如果输出为空或太短，重试一次
        if not output_cpu_usage or len(output_cpu_usage.strip()) < 10:
            logger.warning("CPU输出为空，重试一次...")
            output_cpu_usage = connections.send_command_timing(cpu_cmd, delay_factor=5)
            logger.info(f"CPU输出重试后: {repr(output_cpu_usage)}")

        # 从输出中提取CPU使用率（格式：14% in last 5 seconds）
        match = re.search(r"(\d+)%\s+in last 5 seconds", output_cpu_usage)
        if match:
            logger.info(f"CPU匹配成功: {match.group(1)}%")
            return f"{match.group(1)}%", error_message
        # 备用匹配：直接查找第一个百分比
        match = re.search(r"(\d+)%", output_cpu_usage)
        if match:
            logger.info(f"CPU备用匹配成功: {match.group(1)}%")
            return f"{match.group(1)}%", error_message
        logger.error("并未查询到CPU使用率！")
        return "N/A", error_message
    except Exception as e:
        logger.error(f"错误：【子功能】检查CPU使用率出错！ {e}")
        error_message = "检查CPU使用率失败！"
        return "N/A", error_message


# 第四步：检查内存使用率
def check_memory_usage(connections, vendor=None):
    error_message = ""
    try:
        # 使用多厂商命令映射
        memory_cmd = get_vendor_command(vendor, "memory")
        # 使用 display memory 命令获取内存信息
        output_memory_usage = connections.send_command_timing(memory_cmd, delay_factor=3)
        logger.info(f"内存输出原始内容: {repr(output_memory_usage[:150])}")

        # 内存输出格式：
        #              Total      Used      Free    Shared   Buffers    Cached   FreeRatio
        # Mem:        382808    291956     90852         0         4    189092       23.8%

        # 匹配Mem行的数据：Mem: Total Used Free ... FreeRatio
        match = re.search(r"Mem:\s+(\d+)\s+(\d+)\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+\.?\d*)%", output_memory_usage)
        if match:
            total_kb = int(match.group(1))
            used_kb = int(match.group(2))
            free_ratio = float(match.group(3))
            used_ratio = 100 - free_ratio
            logger.info(f"内存匹配成功: 总内存={total_kb}, 已用={used_kb}, 空闲率={free_ratio}%, 使用率={used_ratio:.1f}%")
            return f"{used_ratio:.1f}%", error_message

        # 备用匹配：直接查找最后一个百分比（FreeRatio）
        matches = re.findall(r"(\d+\.?\d*)%", output_memory_usage)
        if matches:
            free_ratio = float(matches[-1])  # 最后一个百分比是FreeRatio
            used_ratio = 100 - free_ratio
            logger.info(f"内存备用匹配成功: 空闲率={free_ratio}%, 使用率={used_ratio:.1f}%")
            return f"{used_ratio:.1f}%", error_message

        logger.error("并未查询到内存使用率！")
        return "N/A", error_message
    except Exception as e:
        logger.error(f"错误：【子功能】检查内存使用率出错！ {e}")
        error_message = "检查内存使用率失败"
        return "N/A", error_message


# 补充检查设备版本信息
def check_device_version(connections, vendor=None):
    error_message = ""
    try:
        # 使用多厂商命令映射
        version_cmd = get_vendor_command(vendor, "version")
        # 增加延迟时间，确保版本信息完整返回
        version_result = connections.send_command_timing(version_cmd, delay_factor=5)
        if not version_result or version_result.strip() == "":
            # 尝试禁用分页后再查询
            connections.send_command_timing("screen-length disable", delay_factor=1)
            version_result = connections.send_command_timing(version_cmd, delay_factor=5)

        if not version_result or version_result.strip() == "":
            logger.warning("版本信息查询为空")
            return "未知", error_message
        else:
            # 清理版本信息，移除命令前缀（如 >display version）
            cleaned_version = version_result.strip()
            if cleaned_version.startswith('>'):
                first_newline = cleaned_version.find('\n')
                if first_newline != -1:
                    cleaned_version = cleaned_version[first_newline+1:].strip()
            # 返回前100个字符作为版本摘要
            return cleaned_version[:100], error_message
    except Exception as e:
        logger.error(f"错误：【子功能】检查版本信息出错！ {e}")
        error_message = "检查版本信息失败"
        return "未知", error_message


# ============================================================
# 扩展健康检查功能（质变级优化 #2）
# ============================================================

# 检查路由表
def check_routing_table(connections, vendor=None):
    """检查设备路由表，返回路由数量和关键路由信息"""
    error_message = ""
    try:
        # 使用多厂商命令映射
        routing_cmd = get_vendor_command(vendor, "routing")
        output = connections.send_command_timing(routing_cmd, delay_factor=3)
        if not output or len(output.strip()) < 10:
            return {"route_count": 0, "routes": [], "error": "路由表为空或查询失败"}

        # 统计路由数量（排除表头和空行）
        lines = output.split("\n")
        route_count = 0
        routes = []
        for line in lines:
            line = line.strip()
            # 路由条目通常以数字开头（如 192.168.1.0/24）
            if line and not line.startswith("Destination") and not line.startswith("---") and not line.startswith("Total"):
                if "/" in line or "Static" in line or "O " in line or "S " in line:
                    route_count += 1
                    # 提取前5条路由作为示例
                    if len(routes) < 5:
                        routes.append(line[:100])  # 截取前100字符

        return {"route_count": route_count, "routes": routes, "error": error_message}
    except Exception as e:
        logger.error(f"错误：检查路由表出错 {e}")
        return {"route_count": 0, "routes": [], "error": "检查路由表失败"}


# 检查ARP表
def check_arp_table(connections, vendor=None):
    """检查设备ARP表，返回ARP条目数量"""
    error_message = ""
    try:
        # 使用多厂商命令映射
        arp_cmd = get_vendor_command(vendor, "arp")
        output = connections.send_command_timing(arp_cmd, delay_factor=3)
        if not output or len(output.strip()) < 10:
            return {"arp_count": 0, "entries": [], "error": "ARP表为空或查询失败"}

        # 统计ARP条目数量
        lines = output.split("\n")
        arp_count = 0
        entries = []
        for line in lines:
            line = line.strip()
            # ARP条目通常包含IP地址和MAC地址
            if line and not line.startswith("IP Address") and not line.startswith("---") and not line.startswith("Total"):
                if ":" in line or "-" in line:  # MAC地址格式
                    arp_count += 1
                    if len(entries) < 5:
                        entries.append(line[:100])

        return {"arp_count": arp_count, "entries": entries, "error": error_message}
    except Exception as e:
        logger.error(f"错误：检查ARP表出错 {e}")
        return {"arp_count": 0, "entries": [], "error": "检查ARP表失败"}


# 检查MAC地址表
def check_mac_address_table(connections, vendor=None):
    """检查设备MAC地址表，返回MAC条目数量"""
    error_message = ""
    try:
        # 使用多厂商命令映射
        mac_cmd = get_vendor_command(vendor, "mac")
        output = connections.send_command_timing(mac_cmd, delay_factor=3)
        if not output or len(output.strip()) < 10:
            return {"mac_count": 0, "entries": [], "error": "MAC地址表为空或查询失败"}

        # 统计MAC条目数量
        lines = output.split("\n")
        mac_count = 0
        entries = []
        for line in lines:
            line = line.strip()
            # MAC条目通常包含MAC地址和VLAN信息
            if line and not line.startswith("MAC Address") and not line.startswith("---") and not line.startswith("Total"):
                if "-" in line or ":" in line:  # MAC地址格式
                    mac_count += 1
                    if len(entries) < 5:
                        entries.append(line[:100])

        return {"mac_count": mac_count, "entries": entries, "error": error_message}
    except Exception as e:
        logger.error(f"错误：检查MAC地址表出错 {e}")
        return {"mac_count": 0, "entries": [], "error": "检查MAC地址表失败"}


# 检查VLAN信息
def check_vlan_info(connections, vendor=None):
    """检查设备VLAN信息，返回VLAN列表"""
    error_message = ""
    try:
        # 使用多厂商命令映射
        vlan_cmd = get_vendor_command(vendor, "vlan")
        output = connections.send_command_timing(vlan_cmd, delay_factor=3)
        if not output or len(output.strip()) < 10:
            return {"vlan_count": 0, "vlans": [], "error": "VLAN信息为空或查询失败"}

        # 统计VLAN数量
        lines = output.split("\n")
        vlan_count = 0
        vlans = []
        for line in lines:
            line = line.strip()
            # VLAN条目通常以VLAN ID开头
            if line and not line.startswith("VLAN ID") and not line.startswith("---") and not line.startswith("Total"):
                if line.startswith("1") or line.startswith("2") or line.startswith("3") or line.startswith("4") or line.startswith("5"):
                    vlan_count += 1
                    if len(vlans) < 10:
                        vlans.append(line[:80])

        return {"vlan_count": vlan_count, "vlans": vlans, "error": error_message}
    except Exception as e:
        logger.error(f"错误：检查VLAN信息出错 {e}")
        return {"vlan_count": 0, "vlans": [], "error": "检查VLAN信息失败"}


# 检查OSPF邻居
def check_ospf_neighbors(connections, vendor=None):
    """检查设备OSPF邻居状态"""
    error_message = ""
    try:
        # 使用多厂商命令映射
        ospf_cmd = get_vendor_command(vendor, "ospf")
        output = connections.send_command_timing(ospf_cmd, delay_factor=3)
        if not output or len(output.strip()) < 10:
            return {"ospf_count": 0, "neighbors": [], "error": "OSPF邻居为空或查询失败"}

        # 统计OSPF邻居数量
        lines = output.split("\n")
        ospf_count = 0
        neighbors = []
        for line in lines:
            line = line.strip()
            # OSPF邻居条目通常包含Router ID
            if line and not line.startswith("Area") and not line.startswith("---") and not line.startswith("Total"):
                if "Full" in line or "2-Way" in line or "Init" in line:
                    ospf_count += 1
                    if len(neighbors) < 5:
                        neighbors.append(line[:100])

        return {"ospf_count": ospf_count, "neighbors": neighbors, "error": error_message}
    except Exception as e:
        logger.error(f"错误：检查OSPF邻居出错 {e}")
        return {"ospf_count": 0, "neighbors": [], "error": "检查OSPF邻居失败"}


# 检查BGP邻居
def check_bgp_neighbors(connections, vendor=None):
    """检查设备BGP邻居状态"""
    error_message = ""
    try:
        # 使用多厂商命令映射
        bgp_cmd = get_vendor_command(vendor, "bgp")
        output = connections.send_command_timing(bgp_cmd, delay_factor=3)
        if not output or len(output.strip()) < 10:
            return {"bgp_count": 0, "neighbors": [], "error": "BGP邻居为空或查询失败"}

        # 统计BGP邻居数量
        lines = output.split("\n")
        bgp_count = 0
        neighbors = []
        for line in lines:
            line = line.strip()
            # BGP邻居条目通常包含Peer地址
            if line and not line.startswith("Peer") and not line.startswith("---") and not line.startswith("Total"):
                if "Established" in line or "Active" in line or "Connect" in line or "Idle" in line:
                    bgp_count += 1
                    if len(neighbors) < 5:
                        neighbors.append(line[:100])

        return {"bgp_count": bgp_count, "neighbors": neighbors, "error": error_message}
    except Exception as e:
        logger.error(f"错误：检查BGP邻居出错 {e}")
        return {"bgp_count": 0, "neighbors": [], "error": "检查BGP邻居失败"}


# 检查设备环境信息（温度、电源、风扇）
def check_environment_info(connections, vendor=None):
    """检查设备环境信息，包括温度、电源、风扇状态"""
    error_message = ""
    result = {
        "temperature": {"status": "未知", "value": "N/A", "error": ""},
        "power": {"status": "未知", "count": 0, "error": ""},
        "fan": {"status": "未知", "count": 0, "error": ""},
    }

    try:
        # 检查温度
        try:
            # 使用多厂商命令映射
            env_cmd = get_vendor_command(vendor, "environment")
            temp_output = connections.send_command_timing(env_cmd, delay_factor=3)
            if temp_output and len(temp_output.strip()) > 10:
                # 提取温度信息
                lines = temp_output.split("\n")
                for line in lines:
                    if "Temperature" in line or "温度" in line:
                        # 尝试提取温度值
                        import re
                        temp_match = re.search(r"(\d+)\s*°?[Cc]", line)
                        if temp_match:
                            temp_value = int(temp_match.group(1))
                            result["temperature"]["value"] = f"{temp_value}°C"
                            result["temperature"]["status"] = "正常" if temp_value < 60 else "警告" if temp_value < 80 else "危险"
                        break
        except Exception as e:
            result["temperature"]["error"] = f"温度检查失败: {str(e)[:50]}"

        # 检查电源
        try:
            # 使用多厂商命令映射
            power_cmd = get_vendor_command(vendor, "power")
            power_output = connections.send_command_timing(power_cmd, delay_factor=3)
            if power_output and len(power_output.strip()) > 10:
                lines = power_output.split("\n")
                power_count = 0
                for line in lines:
                    if "Normal" in line or "正常" in line:
                        power_count += 1
                result["power"]["count"] = power_count
                result["power"]["status"] = "正常" if power_count > 0 else "异常"
        except Exception as e:
            result["power"]["error"] = f"电源检查失败: {str(e)[:50]}"

        # 检查风扇
        try:
            # 使用多厂商命令映射
            fan_cmd = get_vendor_command(vendor, "fan")
            fan_output = connections.send_command_timing(fan_cmd, delay_factor=3)
            if fan_output and len(fan_output.strip()) > 10:
                lines = fan_output.split("\n")
                fan_count = 0
                for line in lines:
                    if "Normal" in line or "正常" in line:
                        fan_count += 1
                result["fan"]["count"] = fan_count
                result["fan"]["status"] = "正常" if fan_count > 0 else "异常"
        except Exception as e:
            result["fan"]["error"] = f"风扇检查失败: {str(e)[:50]}"

        return result
    except Exception as e:
        logger.error(f"错误：检查环境信息出错 {e}")
        return {"temperature": {"status": "未知", "value": "N/A", "error": str(e)},
                "power": {"status": "未知", "count": 0, "error": str(e)},
                "fan": {"status": "未知", "count": 0, "error": str(e)}}


# 检查STP（生成树）状态
def check_stp_status(connections, vendor=None):
    """检查设备STP状态"""
    error_message = ""
    try:
        # 使用多厂商命令映射
        stp_cmd = get_vendor_command(vendor, "stp")
        output = connections.send_command_timing(stp_cmd, delay_factor=3)
        if not output or len(output.strip()) < 10:
            return {"stp_status": "未知", "root_bridge": "N/A", "error": "STP信息为空或查询失败"}

        # 提取STP状态
        lines = output.split("\n")
        stp_status = "未知"
        root_bridge = "N/A"
        for line in lines:
            if "Root Bridge" in line or "根桥" in line:
                root_bridge = line.strip()[:80]
            if "CIST" in line or "MSTP" in line or "STP" in line:
                stp_status = "运行中"

        return {"stp_status": stp_status, "root_bridge": root_bridge, "error": error_message}
    except Exception as e:
        logger.error(f"错误：检查STP状态出错 {e}")
        return {"stp_status": "未知", "root_bridge": "N/A", "error": "检查STP状态失败"}


# 检查链路聚合状态
def check_link_aggregation(connections, vendor=None):
    """检查设备链路聚合状态"""
    error_message = ""
    try:
        # 使用多厂商命令映射
        link_agg_cmd = get_vendor_command(vendor, "link_agg")
        output = connections.send_command_timing(link_agg_cmd, delay_factor=3)
        if not output or len(output.strip()) < 10:
            return {"agg_count": 0, "agg_groups": [], "error": "链路聚合信息为空或查询失败"}

        # 统计链路聚合组数量
        lines = output.split("\n")
        agg_count = 0
        agg_groups = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("Aggregation") and not line.startswith("---") and not line.startswith("Total"):
                if "Selected" in line or "Unselected" in line:
                    agg_count += 1
                    if len(agg_groups) < 5:
                        agg_groups.append(line[:100])

        return {"agg_count": agg_count, "agg_groups": agg_groups, "error": error_message}
    except Exception as e:
        logger.error(f"错误：检查链路聚合出错 {e}")
        return {"agg_count": 0, "agg_groups": [], "error": "检查链路聚合失败"}


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
        # 3. 添加兼容HCL模拟器的参数
        device_info["global_delay_factor"] = 2
        device_info["timeout"] = 30
        device_info["conn_timeout"] = 10
        device_info["fast_cli"] = False
        
        connections = ConnectHandler(**device_info)
        logger.info("连接成功！")
        logger.info(f"正在检查设备{results['device_name']}({device_info['host']})的各项状态.......")

        # 4. 原有接口检查逻辑不变，直接复用
        try:
            total_interface, up_interface, down_interface, if_error = check_interface_status(connections)
            # 将接口检查结果赋值到字典
            results["total_interface"] = total_interface
            results["up_interface"] = up_interface
            results["down_interface"] = down_interface
            if if_error:
                results["error_message"] += "检查端口状态失败；"
        except Exception as e:
            results["error_message"] += f"检查端口状态失败 {e}；"
            total_interface, up_interface, down_interface = 0, 0, 0
            results["total_interface"] = 0
            results["up_interface"] = 0
            results["down_interface"] = 0

        try:
            CPU_usage, if_error = check_cpu_usage(connections)
            results["CPU_usage"] = CPU_usage  # 将结果赋值到字典
            if if_error:
                results["error_message"] += "检查CPU使用率失败！；"
        except Exception as e:
            results["error_message"] += f"检查CPU使用率失败！ {e}；"
            CPU_usage = "N/A"
            results["CPU_usage"] = CPU_usage

        try:
            memory_usage, if_error = check_memory_usage(connections)
            results["memory_usage"] = memory_usage  # 将结果赋值到字典
            if if_error:
                results["error_message"] += "检查内存使用率失败！；"
        except Exception as e:
            results["error_message"] += f"检查内存使用率失败！ {e}；"
            memory_usage = "N/A"
            results["memory_usage"] = memory_usage
        try:
            version_result, if_error = check_device_version(connections)
            results["version"] = version_result  # 将结果赋值到字典
            if if_error:
                results["error_message"] += "检查设备版本信息失败！；"
        except Exception as e:
            results["error_message"] += f"检查设备版本信息失败！ {e}；"
            version_result = "未知"
            results["version"] = version_result
        device_health_issues = []
        # 1. 关键端口GE1/0/1 DOWN判断（和并发一致）
        # 先从接口结果里判断关键端口状态（单设备需补这段接口解析，下面会给）
        critical_ports_down = False
        # 直接重新获取接口结果，避免变量不存在的问题，和并发解析逻辑完全一致
        try:
            output_interfaces = connections.send_command_timing("display interface brief", delay_factor=2)
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
            try:
                cpu_num = float(results["CPU_usage"].replace("%", ""))
                # 把字符串里的百分号%全部替换成空字符串
                if cpu_num > 88:
                    device_health_issues.append("CPU使用率过高，已经超过88%")
            except ValueError:
                logger.error(f"CPU使用率格式错误: {results['CPU_usage']}")
        # 4. 内存使用率超88%判断（和并发一致）
        if results["memory_usage"] != "N/A":
            try:
                mem_num = float(results["memory_usage"].replace("%", ""))
                if mem_num > 88:
                    device_health_issues.append("内存使用率过高，已经超过88%")
            except ValueError:
                logger.error(f"内存使用率格式错误: {results['memory_usage']}")
        # 列表空时设为["无"]（和并发一致），保证前端展示统一
        device_health_issues = device_health_issues if device_health_issues else ["无"]

        # ============================================================
        # 扩展健康检查项目（质变级优化 #2）
        # ============================================================
        # 检查路由表
        try:
            routing_result = check_routing_table(connections)
            results["routing_table"] = routing_result
            if routing_result.get("error"):
                results["error_message"] += f"路由表检查失败；"
        except Exception as e:
            results["error_message"] += f"路由表检查异常 {e}；"
            results["routing_table"] = {"route_count": 0, "routes": [], "error": str(e)}

        # 检查ARP表
        try:
            arp_result = check_arp_table(connections)
            results["arp_table"] = arp_result
            if arp_result.get("error"):
                results["error_message"] += f"ARP表检查失败；"
        except Exception as e:
            results["error_message"] += f"ARP表检查异常 {e}；"
            results["arp_table"] = {"arp_count": 0, "entries": [], "error": str(e)}

        # 检查MAC地址表
        try:
            mac_result = check_mac_address_table(connections)
            results["mac_address_table"] = mac_result
            if mac_result.get("error"):
                results["error_message"] += f"MAC地址表检查失败；"
        except Exception as e:
            results["error_message"] += f"MAC地址表检查异常 {e}；"
            results["mac_address_table"] = {"mac_count": 0, "entries": [], "error": str(e)}

        # 检查VLAN信息
        try:
            vlan_result = check_vlan_info(connections)
            results["vlan_info"] = vlan_result
            if vlan_result.get("error"):
                results["error_message"] += f"VLAN信息检查失败；"
        except Exception as e:
            results["error_message"] += f"VLAN信息检查异常 {e}；"
            results["vlan_info"] = {"vlan_count": 0, "vlans": [], "error": str(e)}

        # 检查OSPF邻居
        try:
            ospf_result = check_ospf_neighbors(connections)
            results["ospf_neighbors"] = ospf_result
            if ospf_result.get("error"):
                results["error_message"] += f"OSPF邻居检查失败；"
        except Exception as e:
            results["error_message"] += f"OSPF邻居检查异常 {e}；"
            results["ospf_neighbors"] = {"ospf_count": 0, "neighbors": [], "error": str(e)}

        # 检查BGP邻居
        try:
            bgp_result = check_bgp_neighbors(connections)
            results["bgp_neighbors"] = bgp_result
            if bgp_result.get("error"):
                results["error_message"] += f"BGP邻居检查失败；"
        except Exception as e:
            results["error_message"] += f"BGP邻居检查异常 {e}；"
            results["bgp_neighbors"] = {"bgp_count": 0, "neighbors": [], "error": str(e)}

        # 检查环境信息（温度、电源、风扇）
        try:
            env_result = check_environment_info(connections)
            results["environment"] = env_result
            # 检查温度是否过高
            if env_result.get("temperature", {}).get("status") == "危险":
                device_health_issues.append("设备温度过高")
            elif env_result.get("temperature", {}).get("status") == "警告":
                device_health_issues.append("设备温度偏高")
            # 检查电源状态
            if env_result.get("power", {}).get("status") == "异常":
                device_health_issues.append("电源异常")
            # 检查风扇状态
            if env_result.get("fan", {}).get("status") == "异常":
                device_health_issues.append("风扇异常")
        except Exception as e:
            results["error_message"] += f"环境信息检查异常 {e}；"
            results["environment"] = {"temperature": {"status": "未知", "value": "N/A", "error": str(e)},
                                      "power": {"status": "未知", "count": 0, "error": str(e)},
                                      "fan": {"status": "未知", "count": 0, "error": str(e)}}

        # 检查STP状态
        try:
            stp_result = check_stp_status(connections)
            results["stp_status"] = stp_result
            if stp_result.get("error"):
                results["error_message"] += f"STP状态检查失败；"
        except Exception as e:
            results["error_message"] += f"STP状态检查异常 {e}；"
            results["stp_status"] = {"stp_status": "未知", "root_bridge": "N/A", "error": str(e)}

        # 检查链路聚合
        try:
            agg_result = check_link_aggregation(connections)
            results["link_aggregation"] = agg_result
            if agg_result.get("error"):
                results["error_message"] += f"链路聚合检查失败；"
        except Exception as e:
            results["error_message"] += f"链路聚合检查异常 {e}；"
            results["link_aggregation"] = {"agg_count": 0, "agg_groups": [], "error": str(e)}

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
        # 原代码：if device_result["status"] == "成功":  # BUG：status 字段值是 healthy/degraded/failed，不是"成功"
        if device_result.get("check_status") == "成功":  # 修复：使用 check_status 字段判断检查是否成功
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
