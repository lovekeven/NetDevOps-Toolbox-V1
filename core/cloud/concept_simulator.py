"""
云网络概念模拟器
不调用真实API，只定义云网络资源的数据结构，并模拟基础操作。
用于展示项目具备管理云网络资源的抽象能力。
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.models import CloudVPC, CloudSecurityGroup  # 引入创建的云VPC资源这个子类"
from dataclasses import dataclass
from typing import List
import json
from datetime import datetime


# 删除相同的这个类，使用统一模型
# @dataclass
# class CloudVPC:
#     """模拟云VPC资源"""

#     id: str  # VPC 唯一标识符
#     name: str
#     cidr_block: str  # VPC 的主网段
#     region: str  # VPC 是 “地域级资源”，VPC 所属地域
#     status: str = "Available"  # VPC 状态
#     subnets: List[str] = None  # VPC 下的子网列表

#     def to_dict(self):

#         return {
#             "resource_type": "VPC",
#             "id": self.id,
#             "name": self.name,
#             "cidr": self.cidr_block,
#             "region": self.region,
#             "status": self.status,
#             "subnet_count": len(self.subnets) if self.subnets else 0,
#             "managed_by": "NetDevOps Platform (Simulated)",
#         }8个


# @dataclass
# class CloudSecurityGroup:
#     """模拟云安全组资源"""

#     id: str  # 安全组唯一 ID
#     name: str
#     vpc_id: str  # 关联的 VPC ID，这个门卫属于哪个 VPC 地盘
#     ingress_rules: List[dict]  # 入站规则列表，谁可以进这个虚拟地盘
#     egress_rules: List[dict]  # 出站规则列表，谁可以出去这个虚拟地盘

#     def to_dict(self):
#         return {
#             "resource_type": "SecurityGroup",
#             "id": self.id,
#             "name": self.name,
#             "vpc_id": self.vpc_id,
#             "rule_count": len(self.ingress_rules) + len(self.egress_rules),
#             "managed_by": "NetDevOps Platform (Simulated)",
#         }


# 云网络模拟器（封地总管家）
class CloudNetworkSimulator:
    """云网络模拟器"""

    def __init__(self):
        self.resources = self._init_demo_resources()

    def _init_demo_resources(self):
        """使用你的统一模型初始化资源"""
        vpcs = [
            CloudVPC(
                vpc_id="vpc-netdevops-demo-1",
                name="prod-core-network",
                cidr_block="10.0.0.0/16",
                region="cn-east-1",
                status="available",
                subnets=["10.0.1.0/24", "10.0.2.0/24"],
            ),
            CloudVPC(
                vpc_id="vpc-netdevops-demo-2",
                name="dev-test-network",
                cidr_block="192.168.0.0/16",
                region="cn-east-1",
                status="available",
            ),
        ]
        security_groups = [
            CloudSecurityGroup(
                sg_id="sg-netdevops-web",
                name="web-servers",
                vpc_id="vpc-netdevops-demo-1",
                ingress_rules=[
                    {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0"},
                    {"protocol": "tcp", "from_port": 443, "to_port": 443, "cidr": "0.0.0.0/0"},
                ],
                # 只放行 80 端口：from_port:80, to_port:80 → 仅服务器 80 端口允许访问（最常用）
                egress_rules=[{"protocol": "all", "cidr": "0.0.0.0/0"}],
            )
        ]

        return {"vpcs": vpcs, "security_groups": security_groups}

    def get_all_resources(self):
        """获取所有模拟资源"""
        all_resources = []
        for vpc in self.resources[
            "vpcs"
        ]:  # 像以上两个类的模板实例化的时候，也需要写成谁等于谁，只不过在这里是遍历赋值给了vpc
            all_resources.append(vpc.to_dict())

        for sg in self.resources["security_groups"]:
            all_resources.append(sg.to_dict())
        return all_resources

    def get_resource_by_type(self, resource_type):
        """按类型获取资源"""
        if resource_type.lower() == "vpc":
            return [vpc.to_dict() for vpc in self.resources["vpcs"]]
        elif resource_type.lower() == "securitygroup":
            return [sg.to_dict() for sg in self.resources["security_groups"]]
        return []

    def simulate_creating_vpc(self, name, cidr, region):
        """模拟创建VPC"""
        new_vpc = CloudVPC(
            vpc_id=f"vpc-simulated-{datetime.now().strftime('%Y%m%d%H%M%S')}",  # 这里的datetime是用的此脚本的模块
            # strftime() 返回的是字符串
            name=name,
            cidr_block=cidr,
            region=region,
            status="Creating",
        )
        self.resources["vpcs"].append(new_vpc)
        return {
            "operation": "simulate_create_vpc",
            "status": "success",
            "message": "这是一个模拟操作，真实环境需调用云厂商API（如 boto3, huaweicloud-sdk）",
            "resource": new_vpc.to_dict(),
        }


# 全局实例
cloud_simulator = CloudNetworkSimulator()
