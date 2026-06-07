"""
AI 拓扑推测模块
当数据不完整时，AI根据已有数据推测拓扑结构

创新点：AI 驱动的拓扑智能推测
1. 数据完整时：直接构建拓扑
2. 数据不完整时：AI推测多种可能的拓扑方案
3. 用户选择最可能的方案
"""

import json
import requests
import time
import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from utils.log_setup import setup_logger

logger = setup_logger("topo_predictor", "topo_predictor.log")


class TopoPredictor:
    """
    AI 拓扑推测器
    根据已有数据推测拓扑结构
    """

    def __init__(self, api_key):
        self.api_key = api_key
        self.deepseek_URL = "https://qianfan.baidubce.com/v2/chat/completions"
        logger.info("AI 拓扑推测器初始化完成")

    def _call_ai(self, prompt):
        """调用 DeepSeek API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": "deepseek-v3.1-250821",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 5000,
        }
        try:
            response = requests.post(
                self.deepseek_URL, headers=headers, json=data, timeout=120
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"AI 调用失败：{e}")
            return None

    def predict_topology(self, collected_data, known_devices=None):
        """
        根据已有数据推测拓扑结构

        :param collected_data: 已采集的数据 {device_ip: collected_data}
        :param known_devices: 已知设备列表
        :return: 推测的拓扑方案列表
        """
        logger.info("开始 AI 拓扑推测...")

        # 构造提示词
        prompt = self._build_predict_prompt(collected_data, known_devices)

        # 调用 AI
        response = self._call_ai(prompt)

        if not response:
            return None

        # 解析 AI 返回的结果
        try:
            # 尝试从响应中提取 JSON
            topo_plans = self._parse_ai_response(response)
            logger.info(f"AI 推测完成，共 {len(topo_plans)} 种方案")
            return topo_plans
        except Exception as e:
            logger.error(f"解析 AI 响应失败：{e}")
            return None

    def _build_predict_prompt(self, collected_data, known_devices):
        """构造提示词"""
        prompt = """你是一个网络拓扑分析专家。现在有一些网络设备的采集数据，但数据可能不完整。
请根据已有数据，推测可能的网络拓扑结构。

## 已采集的数据：

"""
        # 添加每台设备的数据
        for device_ip, data in collected_data.items():
            prompt += f"### 设备 {device_ip}：\n"

            # 设备信息
            device_info = data.get('device_info', {})
            prompt += f"- 设备名称：{device_info.get('sys_name', '未知')}\n"
            prompt += f"- 设备描述：{device_info.get('sys_descr', '未知')}\n"
            prompt += f"- 厂商：{data.get('vendor', '未知')}\n"

            # LLDP 邻居
            lldp_neighbors = data.get('lldp_neighbors', [])
            if lldp_neighbors:
                prompt += f"- LLDP 邻居（{len(lldp_neighbors)}个）：\n"
                for n in lldp_neighbors:
                    prompt += f"  * {n.get('remote_name', '未知')} ({n.get('remote_ip', '未知')}) - 端口：{n.get('remote_port', '未知')}\n"
            else:
                prompt += "- LLDP 邻居：无（可能未开启LLDP）\n"

            # ARP 表
            arp_table = data.get('arp_table', [])
            if arp_table:
                prompt += f"- ARP 表（{len(arp_table)}条）：\n"
                for arp in arp_table[:10]:  # 只显示前10条
                    prompt += f"  * {arp.get('ip', '?')} -> {arp.get('mac', '?')}\n"

            # MAC 表
            mac_table = data.get('mac_table', [])
            if mac_table:
                prompt += f"- MAC 地址表（{len(mac_table)}条）\n"

            # 路由表
            route_table = data.get('route_table', [])
            if route_table:
                prompt += f"- 路由表（{len(route_table)}条）：\n"
                for route in route_table[:5]:  # 只显示前5条
                    prompt += f"  * {route.get('dest', '?')}/{route.get('mask', '?')} -> {route.get('next_hop', '?')}\n"

            prompt += "\n"

        prompt += """
## 任务要求：

1. 根据已有数据，推测完整的网络拓扑结构
2. 给出 2-3 种可能的拓扑方案
3. 每种方案包括：
   - 方案名称和描述
   - 设备列表（包含推测的设备）
   - 链路列表（设备之间的连接关系）
   - 网络层级（核心层/汇聚层/接入层）
   - 置信度（0-100%）
   - 推测依据

4. 输出格式（JSON）：
```json
{
  "plans": [
    {
      "name": "方案A：三层架构",
      "description": "根据路由表和LLDP数据推测...",
      "confidence": 85,
      "reasoning": "推测依据...",
      "nodes": [
        {"id": "192.168.1.1", "name": "Core-Switch", "type": "switch", "layer": "core"}
      ],
      "links": [
        {"source": "192.168.1.1", "target": "192.168.1.2", "source_port": "GE0/0/1", "target_port": "GE0/0/2"}
      ]
    }
  ]
}
```

请直接输出 JSON，不要有其他内容。
"""
        return prompt

    def _parse_ai_response(self, response):
        """解析 AI 返回的结果"""
        # 尝试提取 JSON
        try:
            # 找到 JSON 开始和结束的位置
            json_start = response.find('{')
            json_end = response.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                result = json.loads(json_str)
                return result.get('plans', [])
        except json.JSONDecodeError:
            pass

        # 如果直接解析失败，尝试修复常见的 JSON 问题
        try:
            # 移除可能的 markdown 代码块标记
            response = response.replace('```json', '').replace('```', '')
            json_start = response.find('{')
            json_end = response.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                result = json.loads(json_str)
                return result.get('plans', [])
        except:
            pass

        logger.error("无法解析 AI 响应为 JSON 格式")
        return []

    def analyze_topology(self, topology_data):
        """
        分析拓扑，给出智能建议

        :param topology_data: 拓扑数据 {nodes: [...], links: [...]}
        :return: 分析结果和建议
        """
        logger.info("开始 AI 拓扑分析...")

        # 构造提示词
        prompt = self._build_analysis_prompt(topology_data)

        # 调用 AI
        response = self._call_ai(prompt)

        if not response:
            return None

        return response

    def _build_analysis_prompt(self, topology_data):
        """构造分析提示词"""
        nodes = topology_data.get('nodes', [])
        links = topology_data.get('links', [])

        prompt = f"""你是一个网络运维专家。请分析以下网络拓扑，给出专业的分析报告和建议。

## 拓扑数据：

### 设备列表（共 {len(nodes)} 台）：
"""
        for node in nodes:
            prompt += f"- {node.get('name', '未知')} ({node.get('ip_address', '未知')}) - {node.get('device_type', '未知')} [{node.get('layer', '未知')}]\n"

        prompt += f"\n### 链路列表（共 {len(links)} 条）：\n"
        for link in links:
            prompt += f"- {link.get('source_node', '?')}:{link.get('source_port', '?')} <-> {link.get('target_node', '?')}:{link.get('target_port', '?')} [{link.get('status', '?')}]\n"

        prompt += """
## 分析要求：

1. **拓扑结构分析**：
   - 这是什么类型的拓扑？（三层架构/两层架构/Spine-Leaf等）
   - 网络层级划分是否合理？

2. **风险评估**：
   - 是否存在单点故障？
   - 哪些设备或链路是关键节点？
   - 是否有冗余不足的地方？

3. **优化建议**：
   - 如何提高网络可靠性？
   - 如何优化网络性能？
   - 是否需要增加设备或链路？

4. **安全建议**：
   - 是否有安全隐患？
   - 如何加强网络安全？

请用中文输出，格式清晰，条理清楚。
"""
        return prompt

    def predict_missing_devices(self, collected_data, target_count=None):
        """
        推测缺失的设备

        :param collected_data: 已采集的数据
        :param target_count: 目标设备数量（可选）
        :return: 推测的设备列表
        """
        logger.info("开始推测缺失设备...")

        # 构造提示词
        prompt = f"""你是一个网络架构师。现在有一些网络设备的数据，但拓扑可能不完整。
请根据已有数据，推测可能缺失的设备。

## 已有设备：
"""
        for device_ip, data in collected_data.items():
            device_info = data.get('device_info', {})
            prompt += f"- {device_info.get('sys_name', device_ip)} ({device_ip})\n"

        prompt += f"""
## 任务：
1. 根据已有设备的路由表、ARP表、LLDP邻居等信息，推测可能缺失的设备
2. 给出每个推测设备的：
   - 可能的IP地址
   - 可能的设备类型（路由器/交换机/终端）
   - 可能的网络层级（核心/汇聚/接入）
   - 推测依据

3. 输出格式（JSON）：
```json
{{
  "predicted_devices": [
    {{
      "ip": "192.168.1.2",
      "name": "汇聚交换机1",
      "type": "switch",
      "layer": "aggregation",
      "reasoning": "根据路由表中的下一跳地址推测..."
    }}
  ]
}}
```

请直接输出 JSON，不要有其他内容。
"""
        # 调用 AI
        response = self._call_ai(prompt)

        if not response:
            return None

        # 解析结果
        try:
            json_start = response.find('{')
            json_end = response.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                result = json.loads(json_str)
                return result.get('predicted_devices', [])
        except:
            pass

        return []


# 全局实例（需要在应用启动时初始化）
topo_predictor = None


def init_topo_predictor(api_key):
    """初始化拓扑推测器"""
    global topo_predictor
    topo_predictor = TopoPredictor(api_key)
    return topo_predictor
