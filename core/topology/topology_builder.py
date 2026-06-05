"""
拓扑构建器
把 SNMP 采集的零散数据拼成完整的拓扑图
核心算法：LLDP 邻居拼接、链路去重、设备分类
"""

import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from utils.log_setup import setup_logger

logger = setup_logger("topology_builder", "topology.log")


class TopologyBuilder:
    """
    拓扑构建器
    输入：SNMP 采集的原始数据
    输出：标准化的拓扑节点 + 链路
    """

    def __init__(self):
        # 存放最终结果
        self.nodes = {}      # {node_id: node_dict}
        self.links = []      # [link_dict, ...]
        self._link_set = set()  # 链路去重用，O(1) 查找
        self.visited = set() # 已访问的设备，防止死循环

    # -----------------------------------------------------------
    # 设备分类
    # -----------------------------------------------------------

    def classify_device(self, sys_descr, vendor=''):
        """
        根据系统描述判断设备类型
        简单粗暴的关键词匹配，够用了
        """
        if not sys_descr:
            return 'switch'

        descr_lower = sys_descr.lower()

        # 路由器关键词
        router_keywords = ['router', 'routing', 'ar ', 'ar-', 'ne40', 'ne8000', 'csr', 'isr']
        for kw in router_keywords:
            if kw in descr_lower:
                return 'router'

        # 防火墙关键词
        firewall_keywords = ['firewall', 'usg', 'secpath', 'asa', 'fortigate']
        for kw in firewall_keywords:
            if kw in descr_lower:
                return 'firewall'

        # 交换机关键词（大部分都是交换机）
        switch_keywords = ['switch', 's57', 's67', 's77', 's127', 's93', 'catalyst', 'nexus']
        for kw in switch_keywords:
            if kw in descr_lower:
                return 'switch'

        # 默认当交换机
        return 'switch'

    def guess_layer(self, device_type, neighbors_count):
        """
        根据设备类型和邻居数量猜网络层级
        邻居多的大概率是核心层
        """
        if device_type == 'router':
            return 'core'
        elif neighbors_count >= 4:
            return 'core'
        elif neighbors_count >= 2:
            return 'aggregation'
        else:
            return 'access'

    # -----------------------------------------------------------
    # 节点管理
    # -----------------------------------------------------------

    def add_node(self, node_id, name, ip, device_type, vendor, sys_descr='', status='online'):
        """添加一个节点，已存在就更新"""
        if node_id in self.nodes:
            # 更新已有节点
            self.nodes[node_id].update({
                'name': name,
                'status': status,
            })
            return

        self.nodes[node_id] = {
            'node_id': node_id,
            'name': name,
            'ip_address': ip,
            'device_type': device_type,
            'vendor': vendor,
            'sys_descr': sys_descr,
            'status': status,
            'layer': 'access',  # 先默认接入层，后面再调整
        }

    # -----------------------------------------------------------
    # 链路管理
    # -----------------------------------------------------------

    def add_link(self, source, target, source_port='', target_port='', status='up'):
        """
        添加一条链路，自动去重
        A->B 和 B->A 算同一条
        """
        # 用 set 做 O(1) 去重，比遍历 list 快多了
        pair = tuple(sorted([source, target]))
        if pair in self._link_set:
            return

        self._link_set.add(pair)
        self.links.append({
            'source_node': source,
            'target_node': target,
            'source_port': source_port,
            'target_port': target_port,
            'status': status,
            'link_type': 'ethernet',
        })

    # -----------------------------------------------------------
    # 从 LLDP 数据构建拓扑
    # -----------------------------------------------------------

    def build_from_lldp(self, seed_ip, collected_data):
        """
        从采集数据构建拓扑
        :param seed_ip: 种子设备 IP
        :param collected_data: SNMPCollector.collect_all() 的返回值
        """
        logger.info(f"开始构建拓扑，种子设备：{seed_ip}")

        # 1. 先把种子设备加进去
        device_info = collected_data.get('device_info', {})
        vendor = collected_data.get('vendor', 'unknown')
        sys_descr = device_info.get('sys_descr', '')
        device_type = self.classify_device(sys_descr, vendor)

        self.add_node(
            node_id=seed_ip,
            name=device_info.get('sys_name', f'Device-{seed_ip}'),
            ip=seed_ip,
            device_type=device_type,
            vendor=vendor,
            sys_descr=sys_descr,
        )

        # 2. 处理 LLDP 邻居
        neighbors = collected_data.get('lldp_neighbors', [])
        for neighbor in neighbors:
            remote_name = neighbor.get('remote_name', '')
            remote_ip = neighbor.get('remote_ip', '')
            remote_port = neighbor.get('remote_port', '')
            local_port = neighbor.get('local_port', '')

            if not remote_name and not remote_ip:
                continue

            # 用 IP 做节点 ID，没有 IP 就用名字
            neighbor_id = remote_ip if remote_ip else remote_name

            # 把邻居加到节点列表
            # 邻居的类型先默认交换机，等扫描到它的时候再更新
            self.add_node(
                node_id=neighbor_id,
                name=remote_name if remote_name else f'Unknown-{neighbor_id}',
                ip=remote_ip,
                device_type='switch',  # 默认，后面会更新
                vendor='unknown',
            )

            # 添加链路
            self.add_link(
                source=seed_ip,
                target=neighbor_id,
                source_port=local_port,
                target_port=remote_port,
            )

        # 3. 处理 ARP 表（发现终端设备）
        arp_table = collected_data.get('arp_table', [])
        local_ports = collected_data.get('local_ports', [])
        up_ports = [p for p in local_ports if p['status'] == 'up']

        # ARP 表里的 IP 如果不在 LLDP 邻居里，可能是终端
        lldp_ips = set()
        for n in neighbors:
            if n.get('remote_ip'):
                lldp_ips.add(n['remote_ip'])

        for arp in arp_table:
            arp_ip = arp.get('ip', '')
            if arp_ip and arp_ip not in lldp_ips and arp_ip != seed_ip:
                # 不在 LLDP 邻居里，可能是终端
                self.add_node(
                    node_id=arp_ip,
                    name=f'Terminal-{arp_ip}',
                    ip=arp_ip,
                    device_type='pc',
                    vendor='unknown',
                    status='online',
                )
                # 终端连到种子设备（简化处理）
                self.add_link(
                    source=seed_ip,
                    target=arp_ip,
                    source_port='',
                    target_port='',
                )

        # 4. 更新网络层级
        self._update_layers()

        logger.info(f"拓扑构建完成：{len(self.nodes)} 个节点，{len(self.links)} 条链路")

    # -----------------------------------------------------------
    # 更新网络层级
    # -----------------------------------------------------------

    def _update_layers(self):
        """根据邻居数量更新设备层级"""
        # 统计每个设备的邻居数
        neighbor_count = {}
        for link in self.links:
            src = link['source_node']
            tgt = link['target_node']
            neighbor_count[src] = neighbor_count.get(src, 0) + 1
            neighbor_count[tgt] = neighbor_count.get(tgt, 0) + 1

        # 更新层级
        for node_id, node in self.nodes.items():
            count = neighbor_count.get(node_id, 0)
            node['layer'] = self.guess_layer(node['device_type'], count)

    # -----------------------------------------------------------
    # 获取结果
    # -----------------------------------------------------------

    def get_nodes_list(self):
        """返回节点列表"""
        return list(self.nodes.values())

    def get_links_list(self):
        """返回链路列表"""
        return self.links

    def get_topology_data(self):
        """返回完整的拓扑数据（给 API 用）"""
        return {
            'nodes': self.get_nodes_list(),
            'links': self.get_links_list(),
            'metadata': {
                'device_count': len(self.nodes),
                'link_count': len(self.links),
            }
        }

    # -----------------------------------------------------------
    # 打印拓扑（调试用）
    # -----------------------------------------------------------

    def print_topology(self):
        """打印拓扑信息，调试用"""
        print(f"\n{'='*50}")
        print(f"拓扑概览：{len(self.nodes)} 个节点，{len(self.links)} 条链路")
        print(f"{'='*50}")

        print("\n设备列表：")
        for node_id, node in self.nodes.items():
            icon = {'router': '🌐', 'switch': '🔀', 'firewall': '🛡️', 'pc': '💻'}.get(node['device_type'], '❓')
            print(f"  {icon} {node['name']} ({node['ip_address']}) - {node['device_type']} [{node['layer']}]")

        print("\n链路列表：")
        for link in self.links:
            src_name = self.nodes.get(link['source_node'], {}).get('name', link['source_node'])
            tgt_name = self.nodes.get(link['target_node'], {}).get('name', link['target_node'])
            src_port = f":{link['source_port']}" if link['source_port'] else ''
            tgt_port = f":{link['target_port']}" if link['target_port'] else ''
            print(f"  {src_name}{src_port} <--> {tgt_name}{tgt_port} [{link['status']}]")

        print(f"{'='*50}\n")


# ============================================================
# 测试用
# ============================================================

if __name__ == '__main__':
    # 模拟测试数据
    fake_data = {
        'device_info': {
            'ip': '192.168.1.1',
            'sys_descr': 'H3C S5720 Switch',
            'sys_name': 'Core-Switch',
        },
        'vendor': 'h3c',
        'lldp_neighbors': [
            {'remote_name': 'SW2', 'remote_ip': '192.168.1.2', 'remote_port': 'GE0/0/1', 'local_port': 'GE0/0/1'},
            {'remote_name': 'SW3', 'remote_ip': '192.168.1.3', 'remote_port': 'GE0/0/2', 'local_port': 'GE0/0/2'},
        ],
        'arp_table': [
            {'ip': '192.168.1.100', 'mac': 'aa:bb:cc:dd:ee:ff'},
            {'ip': '192.168.1.101', 'mac': '11:22:33:44:55:66'},
        ],
        'local_ports': [
            {'index': '1', 'name': 'GE0/0/1', 'status': 'up'},
            {'index': '2', 'name': 'GE0/0/2', 'status': 'up'},
        ],
    }

    builder = TopologyBuilder()
    builder.build_from_lldp('192.168.1.1', fake_data)
    builder.print_topology()
