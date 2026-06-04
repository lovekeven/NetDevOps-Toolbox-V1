"""
SNMP 采集模块
用 pysnmp 读取设备的 LLDP 邻居、ARP 表、系统信息
支持华为/H3C/Cisco 真机和模拟器
"""

import asyncio
import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from utils.log_setup import setup_logger

logger = setup_logger("snmp_collector", "topology.log")

# pysnmp 相关导入
try:
    from pysnmp.hlapi.v3arch.asyncio import (
        get_cmd, next_cmd, bulk_cmd,
        SnmpEngine, CommunityData, UsmUserData,
        UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity,
        usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol,
        usmDESPrivProtocol, usmAesCfb128Protocol,
        OctetString
    )
    PYSNMP_AVAILABLE = True
except ImportError:
    PYSNMP_AVAILABLE = False
    logger.warning("pysnmp 没装，SNMP 功能用不了")

# ============================================================
# 常用 OID 定义
# ============================================================

# 系统信息
OID_SYS_DESCR = '1.3.6.1.2.1.1.1.0'      # 设备描述
OID_SYS_NAME = '1.3.6.1.2.1.1.5.0'       # 设备名称
OID_SYS_UPTIME = '1.3.6.1.2.1.1.3.0'     # 运行时间

# LLDP 邻居表（标准 MIB）
OID_LLDP_REM_TABLE = '1.0.8802.1.1.2.1.4.1.1'
OID_LLDP_REM_SYS_NAME = '1.0.8802.1.1.2.1.4.1.1.9'    # 远端设备名
OID_LLDP_REM_PORT_ID = '1.0.8802.1.1.2.1.4.1.1.7'     # 远端端口ID
OID_LLDP_REM_MAN_ADDR = '1.0.8802.1.1.2.1.4.2.1.4'    # 远端管理地址

# LLDP 本地端口信息
OID_LLDP_LOC_PORT_ID = '1.0.8802.1.1.2.1.3.7.1.3'     # 本地端口ID

# ARP 表
OID_ARP_TABLE = '1.3.6.1.2.1.4.22.1.2'   # ipNetToMediaPhysAddress

# 接口表
OID_IF_TABLE = '1.3.6.1.2.1.2.2.1.2'     # ifDescr
OID_IF_STATUS = '1.3.6.1.2.1.2.2.1.8'    # ifOperStatus

# 华为私有 LLDP MIB
OID_HW_LLDP_REM_SYS_NAME = '1.3.6.1.4.1.2011.5.25.134.1.4.1.9'
OID_HW_LLDP_REM_PORT_ID = '1.3.6.1.4.1.2011.5.25.134.1.4.1.7'

# H3C 私有 LLDP MIB
OID_H3C_LLDP_REM_SYS_NAME = '1.3.6.1.4.1.25506.11.1.2.1.4.1.1.9'

# Cisco 私有 LLDP MIB
OID_CISCO_LLDP_REM_SYS_NAME = '1.3.6.1.4.1.9.9.23.1.2.1.1.6'


class SNMPCollector:
    """
    SNMP 采集器
    负责和设备打交道，拿回 LLDP 邻居、ARP、系统信息等原始数据
    """

    def __init__(self, ip, community='public', port=161, version='v2c', timeout=3, retries=2):
        """
        初始化 SNMP 采集器
        :param ip: 设备IP
        :param community: SNMP 团体名（v2c用）
        :param port: SNMP 端口
        :param version: SNMP版本 v2c/v3
        :param timeout: 超时秒数
        :param retries: 重试次数
        """
        self.ip = ip
        self.community = community
        self.port = port
        self.version = version
        self.timeout = timeout
        self.retries = retries
        self.snmp_engine = None
        self.auth_data = None
        self.transport_target = None

        if not PYSNMP_AVAILABLE:
            logger.error("pysnmp 没装，无法初始化 SNMP 采集器")
            return

        self._setup_snmp()

    def _setup_snmp(self):
        """配置 SNMP 连接参数"""
        self.snmp_engine = SnmpEngine()

        if self.version == 'v2c':
            self.auth_data = CommunityData(self.community)
        # v3 的话后面再加，先把 v2c 跑通

        self.transport_target = UdpTransportTarget(
            (self.ip, self.port),
            timeout=self.timeout,
            retries=self.retries
        )

    # -----------------------------------------------------------
    # 基础 SNMP 操作
    # -----------------------------------------------------------

    async def snmp_get(self, oid):
        """单个 OID 获取"""
        try:
            error_indication, error_status, error_index, var_binds = await get_cmd(
                self.snmp_engine,
                self.auth_data,
                self.transport_target,
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )

            if error_indication:
                logger.warning(f"SNMP GET 错误 [{self.ip}]: {error_indication}")
                return None
            if error_status:
                logger.warning(f"SNMP GET 状态错误 [{self.ip}]: {error_status.prettyPrint()}")
                return None

            for var_bind in var_binds:
                return var_bind[1]  # 返回值
            return None
        except Exception as e:
            logger.error(f"SNMP GET 异常 [{self.ip}]: {e}")
            return None

    async def snmp_walk(self, oid):
        """遍历 OID 子树，返回 (oid, value) 列表"""
        results = []
        try:
            async for (error_indication, error_status, error_index, var_binds) in next_cmd(
                self.snmp_engine,
                self.auth_data,
                self.transport_target,
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
                lexicographicMode=False
            ):
                if error_indication:
                    logger.warning(f"SNMP WALK 错误 [{self.ip}]: {error_indication}")
                    break
                if error_status:
                    logger.warning(f"SNMP WALK 状态错误 [{self.ip}]: {error_status.prettyPrint()}")
                    break

                for var_bind in var_binds:
                    results.append((str(var_bind[0]), var_bind[1]))
        except Exception as e:
            logger.error(f"SNMP WALK 异常 [{self.ip}]: {e}")

        return results

    # -----------------------------------------------------------
    # 设备信息采集
    # -----------------------------------------------------------

    async def get_device_info(self):
        """获取设备基本信息：系统描述、主机名"""
        info = {
            'ip': self.ip,
            'sys_descr': '',
            'sys_name': '',
        }

        # 拿设备描述
        descr = await self.snmp_get(OID_SYS_DESCR)
        if descr:
            info['sys_descr'] = str(descr)

        # 拿设备名
        name = await self.snmp_get(OID_SYS_NAME)
        if name:
            info['sys_name'] = str(name)

        logger.info(f"设备信息采集完成 [{self.ip}]: {info['sys_name']}")
        return info

    # -----------------------------------------------------------
    # LLDP 邻居采集
    # -----------------------------------------------------------

    async def get_lldp_neighbors(self):
        """
        读取 LLDP 邻居表
        返回邻居列表：[{local_port, remote_name, remote_port, remote_ip}, ...]
        """
        neighbors = []

        # 先用标准 MIB 试试
        rem_sys_name_list = await self.snmp_walk(OID_LLDP_REM_SYS_NAME)
        rem_port_id_list = await self.snmp_walk(OID_LLDP_REM_PORT_ID)
        rem_man_addr_list = await self.snmp_walk(OID_LLDP_REM_MAN_ADDR)

        # 标准 MIB 没数据的话，试试华为私有 MIB
        if not rem_sys_name_list:
            logger.info(f"标准 LLDP MIB 没数据，试试华为私有 MIB [{self.ip}]")
            rem_sys_name_list = await self.snmp_walk(OID_HW_LLDP_REM_SYS_NAME)
            rem_port_id_list = await self.snmp_walk(OID_HW_LLDP_REM_PORT_ID)

        # 还没数据，试 H3C
        if not rem_sys_name_list:
            logger.info(f"华为 MIB 没数据，试试 H3C 私有 MIB [{self.ip}]")
            rem_sys_name_list = await self.snmp_walk(OID_H3C_LLDP_REM_SYS_NAME)

        # 还是没有，试 Cisco
        if not rem_sys_name_list:
            logger.info(f"H3C MIB 没数据，试试 Cisco 私有 MIB [{self.ip}]")
            rem_sys_name_list = await self.snmp_walk(OID_CISCO_LLDP_REM_SYS_NAME)

        if not rem_sys_name_list:
            logger.warning(f"LLDP 邻居表为空 [{self.ip}]，可能设备没开 LLDP 或者不支持")
            return neighbors

        # 解析邻居数据
        # LLDP 表的索引结构比较复杂，一般是 lldpRemTimeMark.lldpRemLocalPortNum.lldpRemIndex
        # 我们按索引来匹配远端名、远端端口、远端地址

        # 先把数据按索引存起来
        name_dict = {}
        for oid, val in rem_sys_name_list:
            # 从 OID 末尾提取索引
            index = oid.split('.')[-3:] if '.' in oid else [oid]
            key = '.'.join(index[-3:]) if len(index) >= 3 else oid.split('.')[-1]
            name_dict[key] = str(val)

        port_dict = {}
        for oid, val in rem_port_id_list:
            index = oid.split('.')[-3:] if '.' in oid else [oid]
            key = '.'.join(index[-3:]) if len(index) >= 3 else oid.split('.')[-1]
            port_dict[key] = str(val)

        addr_dict = {}
        for oid, val in rem_man_addr_list:
            # 管理地址的 OID 更长，取最后几段
            parts = oid.split('.')
            key = '.'.join(parts[-5:]) if len(parts) >= 5 else oid
            # 把 bytes 转成 IP
            if isinstance(val, bytes):
                addr_dict[key] = '.'.join(str(b) for b in val)
            else:
                addr_dict[key] = str(val)

        # 组装邻居信息
        for key, remote_name in name_dict.items():
            neighbor = {
                'remote_name': remote_name,
                'remote_port': port_dict.get(key, '未知'),
                'remote_ip': addr_dict.get(key, ''),
                'local_port': '',  # 后面从本地端口表补充
            }
            neighbors.append(neighbor)

        logger.info(f"LLDP 邻居采集完成 [{self.ip}]：发现 {len(neighbors)} 个邻居")
        return neighbors

    # -----------------------------------------------------------
    # 本地端口信息
    # -----------------------------------------------------------

    async def get_local_ports(self):
        """获取本地端口列表和状态"""
        ports = []

        # 端口描述
        if_descr_list = await self.snmp_walk(OID_IF_TABLE)
        # 端口状态
        if_status_list = await self.snmp_walk(OID_IF_STATUS)

        # 组装
        status_dict = {}
        for oid, val in if_status_list:
            port_index = oid.split('.')[-1]
            # 1=up, 2=down
            status_dict[port_index] = 'up' if int(val) == 1 else 'down'

        for oid, val in if_descr_list:
            port_index = oid.split('.')[-1]
            ports.append({
                'index': port_index,
                'name': str(val),
                'status': status_dict.get(port_index, 'unknown')
            })

        logger.info(f"端口信息采集完成 [{self.ip}]：共 {len(ports)} 个端口")
        return ports

    # -----------------------------------------------------------
    # ARP 表采集
    # -----------------------------------------------------------

    async def get_arp_table(self):
        """读取 ARP 表，获取 IP-MAC 映射"""
        arp_entries = []

        arp_list = await self.snmp_walk(OID_ARP_TABLE)

        for oid, val in arp_list:
            # OID 格式：1.3.6.1.2.1.4.22.1.2.ifIndex.ipAddr
            parts = oid.split('.')
            if len(parts) >= 5:
                # 提取 IP 地址（最后4段）
                ip_parts = parts[-4:]
                ip_addr = '.'.join(ip_parts)

                # MAC 地址
                mac = ''
                if isinstance(val, bytes) and len(val) == 6:
                    mac = ':'.join(f'{b:02x}' for b in val)

                arp_entries.append({
                    'ip': ip_addr,
                    'mac': mac,
                })

        logger.info(f"ARP 表采集完成 [{self.ip}]：共 {len(arp_entries)} 条")
        return arp_entries

    # -----------------------------------------------------------
    # 厂商识别
    # -----------------------------------------------------------

    def detect_vendor(self, sys_descr):
        """根据系统描述识别厂商"""
        descr_lower = sys_descr.lower()

        if 'huawei' in descr_lower or 'hwp' in descr_lower:
            return 'huawei'
        elif 'h3c' in descr_lower or 'hirschmann' in descr_lower:
            return 'h3c'
        elif 'cisco' in descr_lower:
            return 'cisco'
        elif 'ruijie' in descr_lower:
            return 'ruijie'
        else:
            return 'unknown'

    # -----------------------------------------------------------
    # 一键采集全部信息
    # -----------------------------------------------------------

    async def collect_all(self):
        """
        一次性采集所有信息
        返回：{device_info, lldp_neighbors, arp_table, local_ports, vendor}
        """
        logger.info(f"开始全面采集 [{self.ip}]")

        # 并发采集，快一点
        device_info, lldp_neighbors, arp_table, local_ports = await asyncio.gather(
            self.get_device_info(),
            self.get_lldp_neighbors(),
            self.get_arp_table(),
            self.get_local_ports(),
        )

        # 识别厂商
        vendor = self.detect_vendor(device_info.get('sys_descr', ''))
        device_info['vendor'] = vendor

        result = {
            'device_info': device_info,
            'lldp_neighbors': lldp_neighbors,
            'arp_table': arp_table,
            'local_ports': local_ports,
            'vendor': vendor,
        }

        logger.info(f"全面采集完成 [{self.ip}]：厂商={vendor}，邻居={len(lldp_neighbors)}个，ARP={len(arp_table)}条")
        return result


# ============================================================
# 测试用
# ============================================================

async def test_collect(ip, community='public'):
    """测试采集指定设备"""
    collector = SNMPCollector(ip, community=community)
    result = await collector.collect_all()

    print(f"\n{'='*50}")
    print(f"设备：{result['device_info']['sys_name']} ({ip})")
    print(f"厂商：{result['vendor']}")
    print(f"描述：{result['device_info']['sys_descr'][:80]}")
    print(f"\nLLDP 邻居（{len(result['lldp_neighbors'])}个）：")
    for n in result['lldp_neighbors']:
        print(f"  -> {n['remote_name']} ({n['remote_ip']}) 端口:{n['remote_port']}")
    print(f"\nARP 表（{len(result['arp_table'])}条）：")
    for a in result['arp_table'][:10]:
        print(f"  {a['ip']} -> {a['mac']}")
    print(f"\n本地端口（{len(result['local_ports'])}个）：")
    for p in result['local_ports'][:10]:
        print(f"  {p['name']} [{p['status']}]")
    print(f"{'='*50}")

    return result


if __name__ == '__main__':
    # 测试一下
    if len(sys.argv) > 1:
        test_ip = sys.argv[1]
        test_community = sys.argv[2] if len(sys.argv) > 2 else 'public'
        asyncio.run(test_collect(test_ip, test_community))
    else:
        print("用法: python snmp_collector.py <设备IP> [community]")
        print("例如: python snmp_collector.py 192.168.1.1 public")
