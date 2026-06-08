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
    # 广度优先多层扫描（核心算法）
    # -----------------------------------------------------------

    async def build_topology_bfs(self, seed_ip, community='public', max_depth=3, snmp_version='v2c',
                                  username='', auth_protocol='none', auth_password='',
                                  priv_protocol='none', priv_password=''):
        """
        广度优先扫描全网拓扑
        从种子设备开始，逐层发现邻居的邻居，直到没有新设备

        :param seed_ip: 种子设备IP
        :param community: SNMP团体名（v2c用）
        :param max_depth: 最大扫描深度，防止死循环（默认3层）
        :param snmp_version: SNMP版本 v2c/v3
        :param username: v3用户名
        :param auth_protocol: v3认证协议
        :param auth_password: v3认证密码
        :param priv_protocol: v3加密协议
        :param priv_password: v3加密密码
        """
        from core.topology.snmp_collector import SNMPCollector
        import asyncio

        logger.info(f"开始广度优先扫描，种子设备：{seed_ip}，最大深度：{max_depth}")

        # 待扫描队列：(设备IP, 深度)
        queue = [(seed_ip, 0)]

        while queue:
            current_ip, depth = queue.pop(0)  # FIFO，广度优先

            # 跳过已访问的设备
            if current_ip in self.visited:
                continue

            # 超过最大深度就停
            if depth >= max_depth:
                logger.info(f"达到最大深度 {max_depth}，停止扫描 [{current_ip}]")
                continue

            # 标记为已访问
            self.visited.add(current_ip)
            logger.info(f"扫描设备 [{current_ip}]，当前深度：{depth}")

            try:
                # 创建采集器，根据版本传不同参数
                if snmp_version == 'v3':
                    collector = SNMPCollector(
                        current_ip, version='v3',
                        username=username,
                        auth_protocol=auth_protocol,
                        auth_password=auth_password,
                        priv_protocol=priv_protocol,
                        priv_password=priv_password,
                    )
                else:
                    collector = SNMPCollector(current_ip, community=community)

                # 采集这台设备的所有信息
                collected_data = await collector.collect_all()

                # 把这台设备的信息加入拓扑
                self._add_device_to_topology(current_ip, collected_data)

                # 把这台设备的邻居加入待扫描队列
                neighbors = collected_data.get('lldp_neighbors', [])
                for neighbor in neighbors:
                    neighbor_ip = neighbor.get('remote_ip', '')
                    if neighbor_ip and neighbor_ip not in self.visited:
                        queue.append((neighbor_ip, depth + 1))
                        logger.info(f"发现新邻居 [{neighbor_ip}]，加入扫描队列（深度 {depth + 1}）")

            except Exception as e:
                logger.error(f"扫描设备 [{current_ip}] 失败：{e}")
                continue

        # 扫描完成，更新网络层级
        self._update_layers()

        logger.info(f"广度优先扫描完成：{len(self.nodes)} 个节点，{len(self.links)} 条链路")

    def _add_device_to_topology(self, device_ip, collected_data):
        """
        把一台设备的采集数据加入拓扑
        和 build_from_lldp 类似，但不重置已有数据
        """
        # 1. 添加设备本身
        device_info = collected_data.get('device_info', {})
        vendor = collected_data.get('vendor', 'unknown')
        sys_descr = device_info.get('sys_descr', '')
        device_type = self.classify_device(sys_descr, vendor)

        self.add_node(
            node_id=device_ip,
            name=device_info.get('sys_name', f'Device-{device_ip}'),
            ip=device_ip,
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
            self.add_node(
                node_id=neighbor_id,
                name=remote_name if remote_name else f'Unknown-{neighbor_id}',
                ip=remote_ip,
                device_type='switch',  # 默认，等扫描到它再更新
                vendor='unknown',
            )

            # 添加链路
            self.add_link(
                source=device_ip,
                target=neighbor_id,
                source_port=local_port,
                target_port=remote_port,
            )

        # 3. 处理 ARP 表（发现终端设备）
        arp_table = collected_data.get('arp_table', [])

        # LLDP 邻居的 IP 集合
        lldp_ips = set()
        for n in neighbors:
            if n.get('remote_ip'):
                lldp_ips.add(n['remote_ip'])

        for arp in arp_table:
            arp_ip = arp.get('ip', '')
            if arp_ip and arp_ip not in lldp_ips and arp_ip != device_ip:
                # 不在 LLDP 邻居里，可能是终端
                self.add_node(
                    node_id=arp_ip,
                    name=f'Terminal-{arp_ip}',
                    ip=arp_ip,
                    device_type='pc',
                    vendor='unknown',
                    status='online',
                )
                self.add_link(
                    source=device_ip,
                    target=arp_ip,
                    source_port='',
                    target_port='',
                )

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
            node['layer'] = self.guess_layer(device_type=node['device_type'], neighbors_count=count)

    # -----------------------------------------------------------
    # MAC 双向匹配算法（创新点！）
    # -----------------------------------------------------------

    def build_links_from_mac_table(self, all_devices_data):
        """
        MAC 双向匹配算法
        当 LLDP 失效时，通过 MAC 地址表反向推导链路

        原理：
        设备A的MAC表：MAC-X 从端口1学到
        设备B的MAC表：MAC-X 从端口2学到
        → 说明 A:1 和 B:2 可能相连

        :param all_devices_data: 所有设备的采集数据 {ip: collected_data}
        """
        logger.info("开始 MAC 双向匹配算法...")

        # 1. 收集所有设备的 MAC 表
        # 格式：{device_ip: [(mac, port), ...]}
        device_mac_tables = {}
        for device_ip, data in all_devices_data.items():
            mac_table = data.get('mac_table', [])
            if mac_table:
                device_mac_tables[device_ip] = mac_table

        if not device_mac_tables:
            logger.info("没有 MAC 表数据，跳过 MAC 匹配")
            return

        # 2. 建立 MAC → 出现位置的映射
        # 格式：{mac: [(device_ip, port), ...]}
        mac_locations = {}
        for device_ip, mac_entries in device_mac_tables.items():
            for entry in mac_entries:
                mac = entry.get('mac', '')
                port = entry.get('port', 0)
                if mac:
                    if mac not in mac_locations:
                        mac_locations[mac] = []
                    mac_locations[mac].append((device_ip, port))

        # 3. 找到出现在多台设备上的 MAC，推导链路
        new_links_count = 0
        for mac, locations in mac_locations.items():
            if len(locations) < 2:
                continue  # 只出现在一台设备上，无法推导

            # MAC 出现在多台设备上，可能是链路
            # 但需要排除终端设备（PC、手机等）
            # 终端设备的 MAC 通常只出现在一台交换机的 MAC 表里
            # 而交换机之间的链路，MAC 会出现在两台交换机的 MAC 表里

            # 简单策略：如果 MAC 出现在 2 台设备上，且这两台设备都是网络设备
            # 则认为它们之间有链路
            for i in range(len(locations)):
                for j in range(i + 1, len(locations)):
                    device_a, port_a = locations[i]
                    device_b, port_b = locations[j]

                    # 检查是否都是已知的网络设备（不是终端）
                    node_a = self.nodes.get(device_a)
                    node_b = self.nodes.get(device_b)

                    if node_a and node_b:
                        # 两个都是已知设备，可能是链路
                        # 检查是否已经有这条链路
                        pair = tuple(sorted([device_a, device_b]))
                        if pair not in self._link_set:
                            # 添加链路
                            self.add_link(
                                source=device_a,
                                target=device_b,
                                source_port=str(port_a),
                                target_port=str(port_b),
                            )
                            new_links_count += 1
                            logger.info(f"MAC 匹配发现链路: {device_a}:{port_a} <-> {device_b}:{port_b} (MAC: {mac})")

        # 4. 更新网络层级
        self._update_layers()

        logger.info(f"MAC 双向匹配完成，新增 {new_links_count} 条链路")

    def build_topology_with_mac_fallback(self, seed_ip, community='public', max_depth=3,
                                          snmp_version='v2c', username='', auth_protocol='none',
                                          auth_password='', priv_protocol='none', priv_password=''):
        """
        带 MAC 回退的拓扑发现
        先用 LLDP 发现链路，如果 LLDP 失效，用 MAC 表推导

        这是创新点的核心算法！
        """
        from core.topology.snmp_collector import SNMPCollector
        import asyncio

        logger.info(f"开始带 MAC 回退的拓扑发现，种子：{seed_ip}")

        # 1. 先做 BFS 扫描，收集所有设备的数据
        all_devices_data = {}  # {ip: collected_data}

        queue = [(seed_ip, 0)]
        while queue:
            current_ip, depth = queue.pop(0)

            if current_ip in self.visited:
                continue
            if depth >= max_depth:
                continue

            self.visited.add(current_ip)

            try:
                # 创建采集器
                if snmp_version == 'v3':
                    collector = SNMPCollector(
                        current_ip, version='v3',
                        username=username, auth_protocol=auth_protocol,
                        auth_password=auth_password, priv_protocol=priv_protocol,
                        priv_password=priv_password,
                    )
                else:
                    collector = SNMPCollector(current_ip, community=community)

                # 采集数据
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    collected_data = loop.run_until_complete(collector.collect_all())
                finally:
                    loop.close()
                all_devices_data[current_ip] = collected_data

                # 把设备加入拓扑
                self._add_device_to_topology(current_ip, collected_data)

                # 把邻居加入队列
                neighbors = collected_data.get('lldp_neighbors', [])
                for neighbor in neighbors:
                    neighbor_ip = neighbor.get('remote_ip', '')
                    if neighbor_ip and neighbor_ip not in self.visited:
                        queue.append((neighbor_ip, depth + 1))

            except Exception as e:
                logger.error(f"扫描设备 [{current_ip}] 失败：{e}")
                continue

        # 2. 用 MAC 双向匹配算法补充链路
        logger.info("LLDP 扫描完成，开始 MAC 双向匹配...")
        self.build_links_from_mac_table(all_devices_data)

        # 3. 更新网络层级
        self._update_layers()

        logger.info(f"带 MAC 回退的拓扑发现完成：{len(self.nodes)} 个节点，{len(self.links)} 条链路")

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
