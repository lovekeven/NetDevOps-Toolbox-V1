"""
网络小工具模块
IP扫描、端口扫描、连通测试、LLDP单设备查询
"""

import sys
import os
import subprocess
import socket
import struct
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from utils.log_setup import setup_logger

logger = setup_logger("network_tools", "topology.log")


class NetworkTools:
    """网络工具集"""

    # -----------------------------------------------------------
    # Ping 连通测试
    # -----------------------------------------------------------

    @staticmethod
    def ping(host, count=2, timeout=2):
        """
        Ping 测试
        返回：{host, reachable, rtt_avg, rtt_min, rtt_max}
        """
        try:
            # Windows 用 -n，Linux 用 -c
            param = '-n' if sys.platform == 'win32' else '-c'
            timeout_param = '-w' if sys.platform == 'win32' else '-W'

            cmd = ['ping', param, str(count), timeout_param, str(timeout), host]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout*count+5)

            if result.returncode == 0:
                # 解析 RTT
                output = result.stdout
                rtt_avg = 0
                if 'Average' in output:  # Windows
                    for line in output.split('\n'):
                        if 'Average' in line:
                            rtt_avg = int(line.split('=')[-1].strip().replace('ms', ''))
                elif 'avg' in output:  # Linux
                    for line in output.split('\n'):
                        if 'avg' in line:
                            parts = line.split('=')
                            if len(parts) > 1:
                                rtt_avg = float(parts[1].split('/')[1])

                return {
                    'host': host,
                    'reachable': True,
                    'rtt_avg': rtt_avg,
                }
            else:
                return {'host': host, 'reachable': False, 'rtt_avg': 0}

        except subprocess.TimeoutExpired:
            return {'host': host, 'reachable': False, 'rtt_avg': 0}
        except Exception as e:
            logger.error(f"Ping {host} 失败: {e}")
            return {'host': host, 'reachable': False, 'rtt_avg': 0, 'error': str(e)}

    # -----------------------------------------------------------
    # IP 网段扫描
    # -----------------------------------------------------------

    @staticmethod
    def scan_subnet(network, start=1, end=254, timeout=1, max_threads=50):
        """
        扫描网段内存活主机
        :param network: 网段，如 '192.168.1' 或 '192.168.1.0/24'
        :param start: 起始IP末位
        :param end: 结束IP末位
        :param timeout: 超时秒数
        :param max_threads: 最大线程数
        返回：[{host, reachable}, ...]
        """
        # 处理 CIDR 格式
        if '/' in network:
            network = network.split('/')[0]
            # 简化处理，只取前三段
            network = '.'.join(network.split('.')[:3])

        alive_hosts = []
        total = end - start + 1

        def ping_host(ip):
            return NetworkTools.ping(ip, count=1, timeout=timeout)

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {}
            for i in range(start, end + 1):
                ip = f"{network}.{i}"
                futures[executor.submit(ping_host, ip)] = ip

            for future in as_completed(futures):
                result = future.result()
                if result.get('reachable'):
                    alive_hosts.append(result)
                    logger.info(f"发现存活主机: {result['host']}")

        # 按 IP 排序
        alive_hosts.sort(key=lambda x: tuple(int(p) for p in x['host'].split('.')))

        logger.info(f"网段扫描完成: {network}.{start}-{end}，发现 {len(alive_hosts)} 台存活主机")
        return alive_hosts

    # -----------------------------------------------------------
    # TCP 端口扫描
    # -----------------------------------------------------------

    @staticmethod
    def scan_ports(host, ports=None, timeout=1, max_threads=20):
        """
        扫描指定主机的开放端口
        :param host: 目标 IP
        :param ports: 端口列表，默认常见端口
        :param timeout: 超时秒数
        返回：[{port, open, service}, ...]
        """
        if ports is None:
            # 常见网络设备端口
            ports = [22, 23, 80, 443, 161, 162, 8080, 8443, 9090]

        # 常见端口服务映射
        service_map = {
            22: 'SSH',
            23: 'Telnet',
            80: 'HTTP',
            443: 'HTTPS',
            161: 'SNMP',
            162: 'SNMP Trap',
            8080: 'HTTP-Alt',
            8443: 'HTTPS-Alt',
            9090: 'Web管理',
            3389: 'RDP',
            3306: 'MySQL',
            5432: 'PostgreSQL',
            6379: 'Redis',
            27017: 'MongoDB',
        }

        results = []

        def check_port(port):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((host, port))
                sock.close()
                return {
                    'port': port,
                    'open': result == 0,
                    'service': service_map.get(port, 'Unknown'),
                }
            except Exception:
                return {'port': port, 'open': False, 'service': service_map.get(port, 'Unknown')}

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = [executor.submit(check_port, port) for port in ports]
            for future in as_completed(futures):
                results.append(future.result())

        # 按端口号排序
        results.sort(key=lambda x: x['port'])

        open_count = sum(1 for r in results if r['open'])
        logger.info(f"端口扫描完成: {host}，开放 {open_count}/{len(ports)} 个端口")
        return results

    # -----------------------------------------------------------
    # Traceroute 路径追踪
    # -----------------------------------------------------------

    @staticmethod
    def traceroute(host, max_hops=15, timeout=3):
        """
        Traceroute 路径追踪
        返回：[{hop, ip, rtt}, ...]
        """
        try:
            # Windows 用 tracert，Linux 用 traceroute
            if sys.platform == 'win32':
                cmd = ['tracert', '-d', '-w', str(timeout*1000), '-h', str(max_hops), host]
            else:
                cmd = ['traceroute', '-n', '-w', str(timeout), '-m', str(max_hops), host]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=max_hops*timeout+10)

            hops = []
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line:
                    continue

                # 简单解析
                parts = line.split()
                if parts and parts[0].isdigit():
                    hop_num = int(parts[0])
                    # 找 IP 地址（格式：x.x.x.x）
                    ip = None
                    rtt = 0
                    for part in parts[1:]:
                        if '.' in part and all(c.isdigit() or c == '.' for c in part):
                            ip = part
                        elif 'ms' in part:
                            try:
                                rtt = float(part.replace('ms', ''))
                            except ValueError:
                                pass

                    if ip:
                        hops.append({
                            'hop': hop_num,
                            'ip': ip,
                            'rtt': rtt,
                        })

            logger.info(f"Traceroute 完成: {host}，{len(hops)} 跳")
            return hops

        except subprocess.TimeoutExpired:
            logger.warning(f"Traceroute 超时: {host}")
            return []
        except Exception as e:
            logger.error(f"Traceroute 失败: {host} - {e}")
            return []

    # -----------------------------------------------------------
    # SNMP LLDP 单设备查询
    # -----------------------------------------------------------

    @staticmethod
    def query_device_lldp(ip, community='public'):
        """
        查询单个设备的 LLDP 邻居信息
        需要 pysnmp
        """
        try:
            from core.topology.snmp_collector import SNMPCollector
            import asyncio

            collector = SNMPCollector(ip, community=community)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                device_info = loop.run_until_complete(collector.get_device_info())
                neighbors = loop.run_until_complete(collector.get_lldp_neighbors())
                ports = loop.run_until_complete(collector.get_local_ports())
            finally:
                loop.close()

            return {
                'device': device_info,
                'neighbors': neighbors,
                'ports': ports,
            }
        except ImportError:
            return {'error': 'pysnmp 未安装'}
        except Exception as e:
            logger.error(f"LLDP 查询失败: {ip} - {e}")
            return {'error': str(e)}


# ============================================================
# 测试用
# ============================================================

if __name__ == '__main__':
    tools = NetworkTools()

    # 测试 Ping
    print("\n=== Ping 测试 ===")
    result = tools.ping('127.0.0.1')
    print(f"本机: {result}")

    # 测试端口扫描
    print("\n=== 端口扫描测试 ===")
    ports = tools.scan_ports('127.0.0.1', ports=[22, 80, 443, 8080])
    for p in ports:
        status = '✅' if p['open'] else '❌'
        print(f"  {status} {p['port']}/{p['service']}")
