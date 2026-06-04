"""
SDN 采集模块
对接 Ryu 控制器，获取 OpenFlow 网络拓扑
支持 REST API 方式获取交换机、链路、主机信息
"""

import sys
import os
import requests

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from utils.log_setup import setup_logger

logger = setup_logger("sdn_collector", "topology.log")


class SDNCollector:
    """
    SDN 采集器
    对接 Ryu 控制器的 REST API，获取 OpenFlow 网络拓扑
    """

    def __init__(self, controller_ip='127.0.0.1', controller_port=8080):
        """
        初始化 SDN 采集器
        :param controller_ip: Ryu 控制器 IP
        :param controller_port: Ryu REST API 端口（默认 8080）
        """
        self.controller_url = f"http://{controller_ip}:{controller_port}"
        self.session = requests.Session()
        self.session.timeout = 5

    # -----------------------------------------------------------
    # 基础请求
    # -----------------------------------------------------------

    def _get(self, endpoint):
        """发送 GET 请求到 Ryu REST API"""
        url = f"{self.controller_url}{endpoint}"
        try:
            resp = self.session.get(url)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            logger.error(f"连接 Ryu 控制器失败: {url}")
            return None
        except requests.exceptions.Timeout:
            logger.error(f"请求超时: {url}")
            return None
        except Exception as e:
            logger.error(f"请求异常: {url} - {e}")
            return None

    # -----------------------------------------------------------
    # 获取交换机列表
    # -----------------------------------------------------------

    def get_switches(self):
        """
        获取所有连接的 OpenFlow 交换机
        返回：[{dpid, n_ports, ...}, ...]
        """
        data = self._get('/stats/switches')
        if data is None:
            return []

        # Ryu 返回的是 DPID 列表，如 [1, 2, 3]
        switches = []
        for dpid in data:
            # 获取交换机端口信息
            ports_info = self._get(f'/stats/portdesc/{dpid}')
            ports = []
            if ports_info and str(dpid) in ports_info:
                for port in ports_info[str(dpid)]:
                    # 过滤掉 LOCAL 端口
                    if port.get('port_no') != 4294967294:
                        ports.append({
                            'port_no': port.get('port_no'),
                            'name': port.get('name', '').decode('utf-8', errors='ignore') if isinstance(port.get('name'), bytes) else port.get('name', ''),
                            'hw_addr': port.get('hw_addr', ''),
                            'state': 'up' if port.get('state') == 0 else 'down',
                        })

            switches.append({
                'dpid': dpid,
                'dpid_hex': hex(dpid),
                'n_ports': len(ports),
                'ports': ports,
            })

        logger.info(f"SDN 采集：发现 {len(switches)} 个交换机")
        return switches

    # -----------------------------------------------------------
    # 获取链路信息
    # -----------------------------------------------------------

    def get_links(self):
        """
        获取交换机之间的链路
        返回：[{src_dpid, src_port, dst_dpid, dst_port}, ...]
        """
        data = self._get('/topology/links')
        if data is None:
            return []

        links = []
        for link in data:
            links.append({
                'src_dpid': link.get('src', {}).get('dpid'),
                'src_port': link.get('src', {}).get('port_no'),
                'dst_dpid': link.get('dst', {}).get('dpid'),
                'dst_port': link.get('dst', {}).get('port_no'),
            })

        logger.info(f"SDN 采集：发现 {len(links)} 条链路")
        return links

    # -----------------------------------------------------------
    # 获取主机信息
    # -----------------------------------------------------------

    def get_hosts(self):
        """
        获取接入的主机
        返回：[{mac, ip, dpid, port}, ...]
        """
        data = self._get('/topology/hosts')
        if data is None:
            return []

        hosts = []
        for host in data:
            # 提取 IP 地址
            ipv4_list = host.get('ipv4', [])
            ip_addr = ipv4_list[0] if ipv4_list else ''

            # 提取接入位置
            port_info = host.get('port', {})

            hosts.append({
                'mac': host.get('mac', ''),
                'ip': ip_addr,
                'dpid': port_info.get('dpid'),
                'port_no': port_info.get('port_no'),
            })

        logger.info(f"SDN 采集：发现 {len(hosts)} 个主机")
        return hosts

    # -----------------------------------------------------------
    # 获取流表信息
    # -----------------------------------------------------------

    def get_flow_stats(self, dpid=None):
        """
        获取流表统计信息
        :param dpid: 指定交换机DPID，不传则获取所有
        返回：{dpid: [flow_entry, ...], ...}
        """
        if dpid:
            data = self._get(f'/stats/flow/{dpid}')
        else:
            # 获取所有交换机的流表
            switches = self.get_switches()
            data = {}
            for sw in switches:
                flows = self._get(f'/stats/flow/{sw["dpid"]}')
                if flows:
                    data.update(flows)

        if data is None:
            return {}

        # 解析流表
        result = {}
        for dpid_str, flows in data.items():
            parsed_flows = []
            for flow in flows:
                parsed_flows.append({
                    'table_id': flow.get('table_id'),
                    'priority': flow.get('priority'),
                    'cookie': flow.get('cookie'),
                    'packet_count': flow.get('packet_count'),
                    'byte_count': flow.get('byte_count'),
                    'duration_sec': flow.get('duration_sec'),
                    'match': flow.get('match', {}),
                    'actions': [action for action in flow.get('instructions', [])],
                })
            result[int(dpid_str)] = parsed_flows

        logger.info(f"SDN 采集：获取流表完成")
        return result

    # -----------------------------------------------------------
    # 获取交换机描述信息
    # -----------------------------------------------------------

    def get_switch_desc(self, dpid):
        """获取交换机描述信息"""
        data = self._get(f'/stats/desc/{dpid}')
        if data and str(dpid) in data:
            desc = data[str(dpid)]
            return {
                'manufacturer': desc.get('mfr_desc', ''),
                'hardware': desc.get('hw_desc', ''),
                'software': desc.get('sw_desc', ''),
                'serial': desc.get('serial_num', ''),
                'datapath': desc.get('dp_desc', ''),
            }
        return {}

    # -----------------------------------------------------------
    # 一键采集所有 SDN 信息
    # -----------------------------------------------------------

    def collect_all(self):
        """
        一次性采集所有 SDN 网络信息
        返回标准化的拓扑数据
        """
        logger.info("开始 SDN 全面采集")

        switches = self.get_switches()
        links = self.get_links()
        hosts = self.get_hosts()

        # 获取每个交换机的描述
        for sw in switches:
            desc = self.get_switch_desc(sw['dpid'])
            sw['desc'] = desc

        # 构建标准化拓扑数据
        nodes = []
        edges = []

        # 交换机 -> 节点
        for sw in switches:
            dpid = sw['dpid']
            desc = sw.get('desc', {})
            nodes.append({
                'node_id': f'sdn_sw_{dpid}',
                'name': f'OF-Switch-{dpid}',
                'ip_address': f'DPID:{hex(dpid)}',
                'device_type': 'switch',
                'vendor': 'openflow',
                'model': desc.get('hardware', 'OpenFlow Switch'),
                'status': 'online',
                'layer': 'access',  # 后面可以调整
                'dpid': dpid,
                'n_ports': sw['n_ports'],
                'source': 'sdn',
            })

        # 链路 -> 边
        for link in links:
            src_id = f'sdn_sw_{link["src_dpid"]}'
            dst_id = f'sdn_sw_{link["dst_dpid"]}'
            edges.append({
                'source_node': src_id,
                'target_node': dst_id,
                'source_port': f'Port {link["src_port"]}',
                'target_port': f'Port {link["dst_port"]}',
                'status': 'up',
                'link_type': 'openflow',
            })

        # 主机 -> 终端节点
        for host in hosts:
            host_id = f'sdn_host_{host["mac"].replace(":", "_")}'
            dpid = host.get('dpid')

            nodes.append({
                'node_id': host_id,
                'name': host.get('ip', host['mac']),
                'ip_address': host.get('ip', ''),
                'device_type': 'pc',
                'vendor': 'unknown',
                'status': 'online',
                'layer': 'access',
                'mac': host['mac'],
                'source': 'sdn',
            })

            # 主机连到交换机
            if dpid:
                edges.append({
                    'source_node': f'sdn_sw_{dpid}',
                    'target_node': host_id,
                    'source_port': f'Port {host.get("port_no", "?")}',
                    'target_port': '',
                    'status': 'up',
                    'link_type': 'access',
                })

        result = {
            'switches': switches,
            'links': links,
            'hosts': hosts,
            'nodes': nodes,
            'edges': edges,
            'metadata': {
                'switch_count': len(switches),
                'link_count': len(links),
                'host_count': len(hosts),
                'node_count': len(nodes),
                'controller_url': self.controller_url,
            }
        }

        logger.info(f"SDN 全面采集完成：{len(switches)} 交换机，{len(links)} 链路，{len(hosts)} 主机")
        return result

    # -----------------------------------------------------------
    # 连通性测试
    # -----------------------------------------------------------

    def test_connection(self):
        """测试能否连接到 Ryu 控制器"""
        try:
            resp = self.session.get(f"{self.controller_url}/stats/switches", timeout=3)
            if resp.status_code == 200:
                return {'status': 'connected', 'url': self.controller_url}
            return {'status': 'error', 'code': resp.status_code}
        except Exception as e:
            return {'status': 'disconnected', 'error': str(e)}


# ============================================================
# 测试用
# ============================================================

if __name__ == '__main__':
    import json

    collector = SDNCollector('127.0.0.1', 8080)

    # 测试连接
    conn = collector.test_connection()
    print(f"\n连接测试: {json.dumps(conn, indent=2)}")

    if conn['status'] == 'connected':
        # 采集所有
        result = collector.collect_all()

        print(f"\n{'='*50}")
        print(f"SDN 拓扑概览")
        print(f"{'='*50}")
        print(f"交换机: {result['metadata']['switch_count']}")
        print(f"链路: {result['metadata']['link_count']}")
        print(f"主机: {result['metadata']['host_count']}")

        print(f"\n交换机列表:")
        for sw in result['switches']:
            print(f"  DPID: {hex(sw['dpid'])} ({sw['n_ports']} ports)")

        print(f"\n链路:")
        for link in result['links']:
            print(f"  {hex(link['src_dpid'])}:{link['src_port']} <-> {hex(link['dst_dpid'])}:{link['dst_port']}")

        print(f"\n主机:")
        for host in result['hosts']:
            print(f"  {host['ip']} ({host['mac']}) @ {hex(host['dpid'])}:{host['port_no']}")
    else:
        print("Ryu 控制器未连接，请先启动 Ryu")
