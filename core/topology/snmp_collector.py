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

# pysnmp 相关导入（兼容 4.x 和 6.x 版本）
try:
    from pysnmp.hlapi.asyncio.cmdgen import (
        getCmd, nextCmd, bulkCmd,
        SnmpEngine, CommunityData, UsmUserData,
        UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity,
        usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol,
        usmDESPrivProtocol, usmAesCfb128Protocol,
    )
    from pysnmp.proto.rfc1902 import OctetString
    # 适配：把驼峰命名映射成下划线命名，方便后面代码用
    get_cmd = getCmd
    next_cmd = nextCmd
    bulk_cmd = bulkCmd
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

# MAC 地址表（dot1dTpFdbTable）
OID_MAC_TABLE = '1.3.6.1.2.1.17.4.3.1'           # dot1dTpFdbTable 根节点
OID_MAC_ADDRESS = '1.3.6.1.2.1.17.4.3.1.1'       # dot1dTpFdbAddress - MAC地址
OID_MAC_PORT = '1.3.6.1.2.1.17.4.3.1.2'          # dot1dTpFdbPort - 对应端口
OID_MAC_STATUS = '1.3.6.1.2.1.17.4.3.1.3'        # dot1dTpFdbStatus - 学习状态

# 路由表（ipRouteTable）
OID_ROUTE_TABLE = '1.3.6.1.2.1.4.21.1'           # ipRouteTable 根节点
OID_ROUTE_DEST = '1.3.6.1.2.1.4.21.1.1'          # ipRouteDest - 目的网段
OID_ROUTE_IFINDEX = '1.3.6.1.2.1.4.21.1.2'       # ipRouteIfIndex - 出接口索引
OID_ROUTE_METRIC = '1.3.6.1.2.1.4.21.1.3'        # ipRouteMetric1 - 路由开销
OID_ROUTE_NEXTHOP = '1.3.6.1.2.1.4.21.1.7'       # ipRouteNextHop - 下一跳
OID_ROUTE_MASK = '1.3.6.1.2.1.4.21.1.11'         # ipRouteMask - 子网掩码
OID_ROUTE_TYPE = '1.3.6.1.2.1.4.21.1.8'          # ipRouteType - 路由类型


class SNMPCollector:
    """
    SNMP 采集器
    负责和设备打交道，拿回 LLDP 邻居、ARP、系统信息等原始数据
    支持 v2c 和 v3 两个版本
    """

    def __init__(self, ip, community='public', port=161, version='v2c',
                 timeout=3, retries=2,
                 # v3 专用参数
                 username='', auth_protocol='none', auth_password='',
                 priv_protocol='none', priv_password=''):
        """
        初始化 SNMP 采集器
        :param ip: 设备IP
        :param community: SNMP 团体名（v2c用）
        :param port: SNMP 端口
        :param version: SNMP版本 v2c/v3
        :param timeout: 超时秒数
        :param retries: 重试次数
        :param username: v3 用户名
        :param auth_protocol: v3 认证协议 md5/sha/none
        :param auth_password: v3 认证密码
        :param priv_protocol: v3 加密协议 des/aes/none
        :param priv_password: v3 加密密码
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

        # v3 参数
        self.username = username
        self.auth_protocol = auth_protocol
        self.auth_password = auth_password
        self.priv_protocol = priv_protocol
        self.priv_password = priv_password

        if not PYSNMP_AVAILABLE:
            logger.error("pysnmp 没装，无法初始化 SNMP 采集器")
            return

        self._setup_snmp()

    def _setup_snmp(self):
        """配置 SNMP 连接参数"""
        self.snmp_engine = SnmpEngine()

        if self.version == 'v2c':
            # v2c 用团体名（暗号）认证
            self.auth_data = CommunityData(self.community)
        elif self.version == 'v3':
            # v3 用用户名+密码认证，更安全
            self.auth_data = self._setup_v3_auth()
        else:
            logger.warning(f"不支持的 SNMP 版本: {self.version}，默认用 v2c")
            self.auth_data = CommunityData(self.community)

        self.transport_target = UdpTransportTarget(
            (self.ip, self.port),
            timeout=self.timeout,
            retries=self.retries
        )

    def _setup_v3_auth(self):
        """
        配置 SNMPv3 认证参数
        v3 有三种安全级别：
        1. noAuthNoPriv - 只有用户名，无认证无加密
        2. authNoPriv - 有认证（MD5/SHA），无加密
        3. authPriv - 有认证 + 有加密（DES/AES）
        """
        # 认证协议映射
        auth_proto_map = {
            'md5': usmHMACMD5AuthProtocol,
            'sha': usmHMACSHAAuthProtocol,
            'none': None,
        }

        # 加密协议映射
        priv_proto_map = {
            'des': usmDESPrivProtocol,
            'aes': usmAesCfb128Protocol,
            'none': None,
        }

        auth_proto = auth_proto_map.get(self.auth_protocol.lower())
        priv_proto = priv_proto_map.get(self.priv_protocol.lower())

        # 根据安全级别创建认证对象
        if auth_proto and self.auth_password:
            # 有认证
            if priv_proto and self.priv_password:
                # 有认证 + 有加密（最高安全级别）
                logger.info(f"SNMPv3 authPriv 模式 [{self.ip}]")
                return UsmUserData(
                    self.username,
                    self.auth_password,
                    authProtocol=auth_proto,
                    privKey=self.priv_password,
                    privProtocol=priv_proto,
                )
            else:
                # 有认证 + 无加密
                logger.info(f"SNMPv3 authNoPriv 模式 [{self.ip}]")
                return UsmUserData(
                    self.username,
                    self.auth_password,
                    authProtocol=auth_proto,
                )
        else:
            # 无认证无加密（最低安全级别）
            logger.info(f"SNMPv3 noAuthNoPriv 模式 [{self.ip}]")
            return UsmUserData(self.username)

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
            # pysnmp 6.x 需要用循环调用 next_cmd，而不是 async for
            current_oid = ObjectType(ObjectIdentity(oid))
            while True:
                error_indication, error_status, error_index, var_binds = await next_cmd(
                    self.snmp_engine,
                    self.auth_data,
                    self.transport_target,
                    ContextData(),
                    current_oid,
                    lexicographicMode=False
                )

                if error_indication:
                    logger.warning(f"SNMP WALK 错误 [{self.ip}]: {error_indication}")
                    break
                if error_status:
                    logger.warning(f"SNMP WALK 状态错误 [{self.ip}]: {error_status.prettyPrint()}")
                    break

                if not var_binds:
                    break

                for var_bind in var_binds:
                    oid_str = str(var_bind[0])
                    # 检查是否还在目标 OID 范围内
                    if not oid_str.startswith(oid.rstrip('.')):
                        return results
                    results.append((oid_str, var_bind[1]))
                    current_oid = ObjectType(var_bind[0])
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

        # MIB 回退列表：按优先级尝试不同厂商的私有 MIB
        # 格式：(系统名OID, 端口ID OID, 厂商标识)
        MIB_FALLBACKS = [
            (OID_LLDP_REM_SYS_NAME, OID_LLDP_REM_PORT_ID, "标准"),
            (OID_HW_LLDP_REM_SYS_NAME, OID_HW_LLDP_REM_PORT_ID, "华为"),
            (OID_H3C_LLDP_REM_SYS_NAME, OID_LLDP_REM_PORT_ID, "H3C"),
            (OID_CISCO_LLDP_REM_SYS_NAME, OID_LLDP_REM_PORT_ID, "Cisco"),
        ]

        rem_sys_name_list = []
        rem_port_id_list = []

        for name_oid, port_oid, vendor_name in MIB_FALLBACKS:
            rem_sys_name_list = await self.snmp_walk(name_oid)
            if rem_sys_name_list:
                rem_port_id_list = await self.snmp_walk(port_oid)
                logger.info(f"使用 {vendor_name} MIB 获取到 LLDP 数据 [{self.ip}]")
                break

        # 管理地址用标准 MIB（各厂商通用）
        rem_man_addr_list = await self.snmp_walk(OID_LLDP_REM_MAN_ADDR)

        if not rem_sys_name_list:
            logger.warning(f"LLDP 邻居表为空 [{self.ip}]，可能设备没开 LLDP 或者不支持")
            return neighbors

        # 解析邻居数据
        # LLDP 表索引：lldpRemTimeMark.lldpRemLocalPortNum.lldpRemIndex
        # 取末尾3段作为 key 来匹配同一邻居的不同属性
        def _extract_index(oid, segments=3):
            """从 OID 提取索引 key"""
            parts = oid.split('.')
            return '.'.join(parts[-segments:]) if len(parts) >= segments else parts[-1]

        name_dict = { _extract_index(oid): str(val) for oid, val in rem_sys_name_list }
        port_dict = { _extract_index(oid): str(val) for oid, val in rem_port_id_list }

        # 管理地址的索引更长，取最后5段
        addr_dict = {}
        for oid, val in rem_man_addr_list:
            key = _extract_index(oid, segments=5)
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
    # MAC 地址表采集
    # -----------------------------------------------------------

    async def get_mac_table(self):
        """
        读取 MAC 地址表（dot1dTpFdbTable）
        获取设备学习到的 MAC 地址和对应端口
        返回：[{mac, port, status}, ...]
        """
        mac_entries = []

        # 读取 MAC 地址
        mac_list = await self.snmp_walk(OID_MAC_ADDRESS)
        # 读取对应端口
        port_list = await self.snmp_walk(OID_MAC_PORT)
        # 读取学习状态
        status_list = await self.snmp_walk(OID_MAC_STATUS)

        # 组装数据
        # 状态含义：1=other, 2=invalid, 3=learned, 4=self, 5=mgmt
        status_map = {1: 'other', 2: 'invalid', 3: 'learned', 4: 'self', 5: 'mgmt'}

        # 先把端口和状态做成字典，方便匹配
        port_dict = {}
        for oid, val in port_list:
            # OID 最后一段是端口索引
            index = oid.split('.')[-1]
            port_dict[index] = int(val)

        status_dict = {}
        for oid, val in status_list:
            index = oid.split('.')[-1]
            status_dict[index] = status_map.get(int(val), 'unknown')

        # 遍历 MAC 地址
        for oid, val in mac_list:
            index = oid.split('.')[-1]

            # 解析 MAC 地址（6字节）
            mac = ''
            if isinstance(val, bytes) and len(val) == 6:
                mac = ':'.join(f'{b:02x}' for b in val)
            else:
                mac = str(val)

            mac_entries.append({
                'mac': mac,
                'port': port_dict.get(index, 0),
                'status': status_dict.get(index, 'unknown'),
            })

        logger.info(f"MAC 地址表采集完成 [{self.ip}]：共 {len(mac_entries)} 条")
        return mac_entries

    # -----------------------------------------------------------
    # 路由表采集
    # -----------------------------------------------------------

    async def get_route_table(self):
        """
        读取路由表（ipRouteTable）
        获取设备的路由条目
        返回：[{dest, mask, next_hop, metric, route_type}, ...]
        """
        route_entries = []

        # 读取各字段
        dest_list = await self.snmp_walk(OID_ROUTE_DEST)
        mask_list = await self.snmp_walk(OID_ROUTE_MASK)
        nexthop_list = await self.snmp_walk(OID_ROUTE_NEXTHOP)
        metric_list = await self.snmp_walk(OID_ROUTE_METRIC)
        type_list = await self.snmp_walk(OID_ROUTE_TYPE)

        # 路由类型：1=other, 2=direct, 3=indirect
        route_type_map = {1: 'other', 2: 'direct', 3: 'indirect'}

        # 组装数据
        # 用目的地址做 key，因为同一个目的可能有多条路由
        dest_dict = {}
        for oid, val in dest_list:
            # OID 最后4段是IP地址
            parts = oid.split('.')
            if len(parts) >= 4:
                ip_addr = '.'.join(parts[-4:])
                dest_dict[ip_addr] = {'dest': ip_addr}

        for oid, val in mask_list:
            parts = oid.split('.')
            if len(parts) >= 4:
                ip_addr = '.'.join(parts[-4:])
                if ip_addr in dest_dict:
                    mask_parts = []
                    if isinstance(val, bytes):
                        mask_parts = [str(b) for b in val]
                    else:
                        mask_parts = [str(val)]
                    dest_dict[ip_addr]['mask'] = '.'.join(mask_parts) if mask_parts else str(val)

        for oid, val in nexthop_list:
            parts = oid.split('.')
            if len(parts) >= 4:
                ip_addr = '.'.join(parts[-4:])
                if ip_addr in dest_dict:
                    if isinstance(val, bytes):
                        dest_dict[ip_addr]['next_hop'] = '.'.join(str(b) for b in val)
                    else:
                        dest_dict[ip_addr]['next_hop'] = str(val)

        for oid, val in metric_list:
            parts = oid.split('.')
            if len(parts) >= 4:
                ip_addr = '.'.join(parts[-4:])
                if ip_addr in dest_dict:
                    dest_dict[ip_addr]['metric'] = int(val)

        for oid, val in type_list:
            parts = oid.split('.')
            if len(parts) >= 4:
                ip_addr = '.'.join(parts[-4:])
                if ip_addr in dest_dict:
                    dest_dict[ip_addr]['route_type'] = route_type_map.get(int(val), 'unknown')

        route_entries = list(dest_dict.values())

        logger.info(f"路由表采集完成 [{self.ip}]：共 {len(route_entries)} 条")
        return route_entries

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
        返回：{device_info, lldp_neighbors, arp_table, mac_table, route_table, local_ports, vendor}
        """
        logger.info(f"开始全面采集 [{self.ip}]")

        # 并发采集，快一点（6个任务一起跑）
        device_info, lldp_neighbors, arp_table, mac_table, route_table, local_ports = await asyncio.gather(
            self.get_device_info(),
            self.get_lldp_neighbors(),
            self.get_arp_table(),
            self.get_mac_table(),
            self.get_route_table(),
            self.get_local_ports(),
        )

        # 识别厂商
        vendor = self.detect_vendor(device_info.get('sys_descr', ''))
        device_info['vendor'] = vendor

        result = {
            'device_info': device_info,
            'lldp_neighbors': lldp_neighbors,
            'arp_table': arp_table,
            'mac_table': mac_table,
            'route_table': route_table,
            'local_ports': local_ports,
            'vendor': vendor,
        }

        logger.info(f"全面采集完成 [{self.ip}]：厂商={vendor}，邻居={len(lldp_neighbors)}个，ARP={len(arp_table)}条，MAC={len(mac_table)}条，路由={len(route_table)}条")
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
    print(f"\nMAC 地址表（{len(result['mac_table'])}条）：")
    for m in result['mac_table'][:10]:
        print(f"  {m['mac']} -> 端口:{m['port']} [{m['status']}]")
    print(f"\n路由表（{len(result['route_table'])}条）：")
    for r in result['route_table'][:10]:
        print(f"  {r.get('dest', '?')}/{r.get('mask', '?')} -> {r.get('next_hop', '?')} [{r.get('route_type', '?')}]")
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
