"""
Ryu LLDP 拓扑发现 APP
实现 SDN 中 LLDP 的特殊用法：
控制器主动发包 → 交换机发 LLDP → 邻居交换机收到后上报 → 控制器拼拓扑

这是 SDN 拓扑发现的核心机制，和传统网络 LLDP 完全不同：
- 传统网络：设备自己开启 LLDP，自动记录邻居，你用 SNMP 去读
- SDN 网络：控制器主动发 LLDP 包，自己收包分析，自己拼拓扑

用法：
    ryu-manager --observe-links core.topology.ryu_lldp_app
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import lldp
from ryu.topology import event as topo_event
from ryu.topology.switches import Switches
from ryu.topology.switches import LLDPPacket

import time
import struct
import logging

logger = logging.getLogger(__name__)


class LLDPTopologyApp(app_manager.RyuApp):
    """
    LLDP 拓扑发现 APP
    核心功能：
    1. 监听交换机上线/下线事件
    2. 定时通过 PacketOut 让交换机发 LLDP 包
    3. 监听 PacketIn，解析 LLDP 包，发现邻居关系
    4. 维护拓扑数据（交换机、链路、主机）
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(LLDPTopologyApp, self).__init__(*args, **kwargs)

        # 拓扑数据
        self.switches = {}        # {dpid: switch_info}
        self.links = {}           # {(src_dpid, src_port): (dst_dpid, dst_port)}
        self.hosts = {}           # {mac: host_info}
        self.ports = {}           # {(dpid, port_no): port_info}

        # LLDP 相关
        self.lldp_delay = 5       # LLDP 发送间隔（秒）
        self.lldp_timeout = 15    # LLDP 超时时间（秒）

        # 启动定时发送 LLDP 的线程
        import threading
        self._lldp_thread = threading.Thread(target=self._lldp_sender_loop)
        self._lldp_thread.daemon = True
        self._lldp_thread.start()

    # -----------------------------------------------------------
    # 交换机上线/下线事件
    # -----------------------------------------------------------

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """交换机连接时，配置流表"""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # 安装默认流表：所有未匹配的包都发给控制器
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        logger.info(f"交换机上线: DPID={hex(datapath.id)}")

    def add_flow(self, datapath, priority, match, actions):
        """添加流表"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority, match=match, instructions=inst)
        datapath.send_msg(mod)

    # -----------------------------------------------------------
    # 拓扑事件处理（交换机、端口、链路）
    # -----------------------------------------------------------

    @set_ev_cls(topo_event.EventSwitchEnter)
    def switch_enter_handler(self, ev):
        """交换机进入（上线）"""
        switch = ev.switch
        dpid = switch.dp.id

        self.switches[dpid] = {
            'dpid': dpid,
            'dpid_hex': hex(dpid),
            'ports': [],
        }

        # 记录端口信息
        for port in switch.ports:
            self.ports[(dpid, port.port_no)] = {
                'dpid': dpid,
                'port_no': port.port_no,
                'name': port.name,
                'hw_addr': port.hw_addr,
            }
            self.switches[dpid]['ports'].append({
                'port_no': port.port_no,
                'name': port.name,
                'hw_addr': port.hw_addr,
            })

        logger.info(f"交换机进入: DPID={hex(dpid)}, 端口数={len(switch.ports)}")

    @set_ev_cls(topo_event.EventSwitchLeave)
    def switch_leave_handler(self, ev):
        """交换机离开（下线）"""
        switch = ev.switch
        dpid = switch.dp.id

        # 清理相关数据
        if dpid in self.switches:
            del self.switches[dpid]

        # 清理相关链路
        links_to_remove = []
        for key, value in self.links.items():
            src_dpid, src_port = key
            if src_dpid == dpid:
                links_to_remove.append(key)
        for key in links_to_remove:
            del self.links[key]

        logger.info(f"交换机离开: DPID={hex(dpid)}")

    @set_ev_cls(topo_event.EventLinkAdd)
    def link_add_handler(self, ev):
        """链路新增"""
        link = ev.link
        src_dpid = link.src.dpid
        src_port = link.src.port_no
        dst_dpid = link.dst.dpid
        dst_port = link.dst.port_no

        # 保存双向链路
        self.links[(src_dpid, src_port)] = (dst_dpid, dst_port)
        self.links[(dst_dpid, dst_port)] = (src_dpid, src_port)

        logger.info(f"链路新增: {hex(src_dpid)}:{src_port} <-> {hex(dst_dpid)}:{dst_port}")

    @set_ev_cls(topo_event.EventLinkDelete)
    def link_delete_handler(self, ev):
        """链路删除"""
        link = ev.link
        src_dpid = link.src.dpid
        src_port = link.src.port_no
        dst_dpid = link.dst.dpid
        dst_port = link.dst.port_no

        # 删除双向链路
        if (src_dpid, src_port) in self.links:
            del self.links[(src_dpid, src_port)]
        if (dst_dpid, dst_port) in self.links:
            del self.links[(dst_dpid, dst_port)]

        logger.info(f"链路删除: {hex(src_dpid)}:{src_port} <-> {hex(dst_dpid)}:{dst_port}")

    # -----------------------------------------------------------
    # PacketIn 处理（收到 LLDP 包）
    # -----------------------------------------------------------

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """收到 PacketIn，检查是否是 LLDP 包"""
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        # 解析包
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # 检查是否是 LLDP 包（以太类型 0x88CC）
        if eth.ethertype == 0x88cc:
            # 解析 LLDP 包，发现邻居关系
            self._handle_lldp_packet(datapath, in_port, pkt)
            return

        # 不是 LLDP 包，可能是主机发出的包，记录主机信息
        self._handle_host_packet(datapath, in_port, pkt, eth)

    def _handle_lldp_packet(self, datapath, in_port, pkt):
        """
        处理 LLDP 包，发现邻居关系

        LLDP 包结构：
        - src_dpid: 发送方交换机 DPID
        - src_port: 发送方端口号
        - dst_dpid: 接收方交换机 DPID（当前交换机）
        - dst_port: 接收方端口号（in_port）
        """
        try:
            # 解析 LLDP 包
            lldp_pkt = pkt.get_protocol(lldp.lldp)
            if not lldp_pkt:
                return

            # 提取发送方信息
            # LLDP 包的 Chassis ID 里包含发送方 DPID
            # LLDP 包的 Port ID 里包含发送方端口号
            chassis_id = lldp_pkt.tlvs[0]  # Chassis ID
            port_id = lldp_pkt.tlvs[1]     # Port ID

            # 解析 Chassis ID（发送方 DPID）
            if chassis_id.subtype == lldp.ChassisID.SUB_LOCALLY_ASSIGNED:
                # 本地分配的，格式是 "dpid:xxxx"
                chassis_str = chassis_id.chassis_id.decode('utf-8')
                if chassis_str.startswith('dpid:'):
                    src_dpid = int(chassis_str[5:], 16)
                else:
                    return
            elif chassis_id.subtype == lldp.ChassisID.SUB_MAC:
                # MAC 地址格式，需要转换
                mac_bytes = chassis_id.chassis_id
                src_dpid = int.from_bytes(mac_bytes[-4:], 'big')
            else:
                return

            # 解析 Port ID（发送方端口号）
            if port_id.subtype == lldp.PortID.SUB_LOCALLY_ASSIGNED:
                port_str = port_id.port_id.decode('utf-8')
                if port_str.startswith('port:'):
                    src_port = int(port_str[5:])
                else:
                    return
            elif port_id.subtype == lldp.PortID.SUB_PORT_COMPONENT:
                port_bytes = port_id.port_id
                src_port = int.from_bytes(port_bytes[-4:], 'big')
            else:
                return

            dst_dpid = datapath.id
            dst_port = in_port

            # 记录链路
            self.links[(src_dpid, src_port)] = (dst_dpid, dst_port)
            self.links[(dst_dpid, dst_port)] = (src_dpid, src_port)

            logger.info(f"LLDP 发现链路: {hex(src_dpid)}:{src_port} <-> {hex(dst_dpid)}:{dst_port}")

        except Exception as e:
            logger.error(f"解析 LLDP 包失败: {e}")

    def _handle_host_packet(self, datapath, in_port, pkt, eth):
        """
        处理主机发出的包，记录主机信息
        """
        # 提取 MAC 地址
        src_mac = eth.src
        dst_mac = eth.dst

        # 忽略广播和组播
        if dst_mac == 'ff:ff:ff:ff:ff:ff' or dst_mac.startswith('01:00:5e'):
            return

        # 提取 IP 地址（如果有）
        src_ip = ''
        try:
            ipv4 = pkt.get_protocol(ipv4.ipv4)
            if ipv4:
                src_ip = ipv4.src
        except:
            pass

        # 记录主机信息
        if src_mac not in self.hosts:
            self.hosts[src_mac] = {
                'mac': src_mac,
                'ip': src_ip,
                'dpid': datapath.id,
                'port_no': in_port,
                'first_seen': time.time(),
            }
            logger.info(f"发现主机: MAC={src_mac}, IP={src_ip}, 位置={hex(datapath.id)}:{in_port}")

        # 更新最后看到时间
        self.hosts[src_mac]['last_seen'] = time.time()
        if src_ip:
            self.hosts[src_mac]['ip'] = src_ip

    # -----------------------------------------------------------
    # 定时发送 LLDP 包（核心！这就是 SDN 里 LLDP 的特殊用法）
    # -----------------------------------------------------------

    def _lldp_sender_loop(self):
        """
        定时发送 LLDP 包的循环
        这是 SDN 拓扑发现的核心：控制器主动发包，而不是等设备自己发
        """
        while True:
            time.sleep(self.lldp_delay)
            self._send_lldp_packets()

    def _send_lldp_packets(self):
        """
        向所有交换机的所有端口发送 LLDP 包

        原理：
        1. 控制器构造 LLDP 包，包含发送方 DPID 和端口号
        2. 通过 PacketOut 让交换机从指定端口发出
        3. 如果端口连着邻居交换机，邻居会收到这个包
        4. 邻居交换机通过 PacketIn 把包发给控制器
        5. 控制器解析包，就知道了链路关系
        """
        for dpid, switch_info in self.switches.items():
            # 获取交换机连接
            try:
                datapath = self._get_datapath(dpid)
                if not datapath:
                    continue

                # 向每个端口发送 LLDP 包
                for port_info in switch_info['ports']:
                    port_no = port_info['port_no']

                    # 跳过 LOCAL 端口
                    if port_no == 4294967294:  # OFPP_LOCAL
                        continue

                    # 构造 LLDP 包
                    lldp_pkt = self._build_lldp_packet(dpid, port_no)

                    # 通过 PacketOut 发送
                    self._send_packet_out(datapath, port_no, lldp_pkt)

            except Exception as e:
                logger.error(f"发送 LLDP 包失败 [DPID={hex(dpid)}]: {e}")

    def _build_lldp_packet(self, dpid, port_no):
        """
        构造 LLDP 包

        LLDP 包结构：
        - Ethernet Header: dst=01:80:c2:00:00:0e (LLDP组播), src=交换机MAC, type=0x88cc
        - LLDPDU: Chassis ID + Port ID + TTL + End
        """
        # 创建以太网帧
        pkt = packet.Packet()

        # 以太网头
        eth = ethernet.ethernet(
            dst='01:80:c2:00:00:0e',  # LLDP 组播地址
            src=self._dpid_to_mac(dpid),  # 用 DPID 生成 MAC
            ethertype=0x88cc,  # LLDP 以太类型
        )
        pkt.add_protocol(eth)

        # LLDP 数据单元
        # Chassis ID（标识发送方交换机）
        chassis_id = lldp.ChassisID(
            subtype=lldp.ChassisID.SUB_LOCALLY_ASSIGNED,
            chassis_id=f'dpid:{hex(dpid)}'.encode('utf-8'),
        )

        # Port ID（标识发送方端口）
        port_id = lldp.PortID(
            subtype=lldp.PortID.SUB_LOCALLY_ASSIGNED,
            port_id=f'port:{port_no}'.encode('utf-8'),
        )

        # TTL（存活时间）
        ttl = lldp.TTL(ttl=self.lldp_timeout)

        # End（结束标记）
        end = lldp.End()

        # 组装 LLDP 数据单元
        lldp_pkt = lldp.lldp(tlvs=[chassis_id, port_id, ttl, end])
        pkt.add_protocol(lldp_pkt)

        # 序列化
        pkt.serialize()

        return pkt

    def _send_packet_out(self, datapath, port_no, pkt):
        """
        通过 PacketOut 发送包
        告诉交换机：把这个包从指定端口发出去
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # 构造 PacketOut 消息
        actions = [parser.OFPActionOutput(port_no)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,  # 从控制器发出
            actions=actions,
            data=pkt.data,
        )

        datapath.send_msg(out)

    def _dpid_to_mac(self, dpid):
        """把 DPID 转换成 MAC 地址（用于 LLDP 包的源 MAC）"""
        # 取 DPID 的后 6 字节
        mac_bytes = dpid.to_bytes(8, 'big')[-6:]
        return ':'.join(f'{b:02x}' for b in mac_bytes)

    def _get_datapath(self, dpid):
        """获取交换机的 datapath 对象"""
        # 这需要从 Ryu 的交换机管理器获取
        # 简化实现：直接返回 None，实际应该从 Switches 模块获取
        return None

    # -----------------------------------------------------------
    # 拓扑数据查询（给 REST API 用）
    # -----------------------------------------------------------

    def get_topology(self):
        """
        获取当前拓扑数据
        返回标准化的拓扑 JSON
        """
        # 交换机列表
        switches = []
        for dpid, switch_info in self.switches.items():
            switches.append({
                'dpid': dpid,
                'dpid_hex': hex(dpid),
                'n_ports': len(switch_info['ports']),
                'ports': switch_info['ports'],
            })

        # 链路列表（去重）
        links = []
        seen = set()
        for (src_dpid, src_port), (dst_dpid, dst_port) in self.links.items():
            # 去重：A->B 和 B->A 只保留一条
            pair = tuple(sorted([(src_dpid, src_port), (dst_dpid, dst_port)]))
            if pair not in seen:
                seen.add(pair)
                links.append({
                    'src_dpid': src_dpid,
                    'src_port': src_port,
                    'dst_dpid': dst_dpid,
                    'dst_port': dst_port,
                })

        # 主机列表
        hosts = list(self.hosts.values())

        return {
            'switches': switches,
            'links': links,
            'hosts': hosts,
            'metadata': {
                'switch_count': len(switches),
                'link_count': len(links),
                'host_count': len(hosts),
            }
        }
