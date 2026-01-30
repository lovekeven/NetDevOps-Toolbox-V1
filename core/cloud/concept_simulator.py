"""
云网络概念模拟器
不调用真实API，只定义云网络资源的数据结构，并模拟基础操作。
用于展示项目具备管理云网络资源的抽象能力。
"""

import os
import sys
import yaml
from datetime import datetime

# 新增：定位项目根目录，统一配置路径（兼容项目结构）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
# 新增：引入项目统一日志器+云资源模型
from utils.log_setup import setup_logger
from utils.models import CloudVPC, CloudSecurityGroup  # 引入创建的云VPC资源这个子类"
from dataclasses import dataclass
from typing import List
import json
from datetime import datetime

# 新增：初始化项目统一日志器（指定日志名，区分日志来源，日志文件单独存放）
logger = setup_logger(name="cloud_network_simulator", log_file="cloud_network_simulator.log")


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

        logger.debug("【云网络模拟器】开始初始化，准备加载模拟资源")
        self.resources = self._init_demo_resources()
        logger.debug(
            f"【云网络模拟器】初始化完成，成功加载VPC{len(self.resources['vpcs'])}个、安全组{len(self.resources['security_groups'])}个"
        )

    def _init_demo_resources(self):
        """使用你的统一模型初始化资源"""

        cloud_config_path = os.path.join(ROOT_DIR, "config", "cloud_resources.yaml")
        # 新增：容错处理-检查配置文件是否存在
        if not os.path.exists(cloud_config_path):
            logger.error(f"【云网络模拟器】未找到配置文件，路径：{cloud_config_path}，将初始化空资源")
            return {"vpcs": [], "security_groups": []}

        # 读取并解析YAML配置
        try:
            with open(cloud_config_path, "r", encoding="utf-8") as f:
                cloud_config = yaml.safe_load(f) or {}
            logger.debug(f"【云网络模拟器】成功读取配置文件：{cloud_config_path}")
        except Exception as e:
            logger.error(f"【云网络模拟器】读取配置文件失败，原因：{str(e)}，将初始化空资源", exc_info=True)
            return {"vpcs": [], "security_groups": []}

        vpcs = []
        security_groups = []
        # 新增：从YAML加载模拟VPC（仅过滤resource_mode: sim的资源）
        vpcs_config = cloud_config.get("vpcs", {})
        for vpc_number, vpc_info in vpcs_config.items():
            # 仅处理模拟资源，跳过真实资源
            if vpc_info.get("resource_mode") != "sim":
                logger.debug(f"【云网络模拟器】跳过真实VPC资源：{vpc_number}")
                continue
            try:
                vpc = CloudVPC(
                    vpc_id=vpc_info.get("vpc_id", "unknown"),
                    name=vpc_info.get("name", vpc_number),
                    cidr_block=vpc_info.get("cidr_block", "未知网段"),
                    region=vpc_info.get("region", "cn-hangzhou"),
                    subnets=vpc_info.get("subnets", []),
                    status="running",  # 模拟资源固定状态，与项目逻辑一致
                    create_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                vpcs.append(vpc)
                logger.debug(f"【云网络模拟器】成功加载模拟VPC：{vpc.name}（ID：{vpc.id}）")
            except Exception as e:
                logger.error(f"【云网络模拟器】加载模拟VPC{ vpc_number}失败，原因：{str(e)}", exc_info=True)
                continue

        # 新增：从YAML加载模拟安全组（仅过滤resource_mode: sim的资源）
        sg_config = cloud_config.get("security_groups", {})
        for sg_number, sg_info in sg_config.items():
            # 仅处理模拟资源，跳过真实资源
            if sg_info.get("resource_mode") != "sim":
                logger.debug(f"【云网络模拟器】跳过真实安全组资源：{sg_number}")
                continue
            try:
                sg = CloudSecurityGroup(
                    sg_id=sg_info.get("sg_id", sg_number),
                    name=sg_info.get("name", sg_number),
                    vpc_id=sg_info.get("vpc_id", "未知VPC"),
                    ingress_rules=sg_info.get("ingress_rules", []),
                    egress_rules=sg_info.get("egress_rules", []),
                    status="running",  # 模拟资源固定状态，与项目逻辑一致
                    create_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                security_groups.append(sg)
                logger.debug(f"【云网络模拟器】成功加载模拟安全组：{sg.name}（ID：{sg.id}，关联VPC：{sg.vpc_id}）")
            except Exception as e:
                logger.error(f"【云网络模拟器】加载模拟安全组{ sg_number }失败，原因：{str(e)}", exc_info=True)
                continue

        return {"vpcs": vpcs, "security_groups": security_groups}

    def get_all_resources(self):
        """获取所有模拟资源"""

        logger.info("【云网络模拟器】执行操作：获取所有模拟资源")
        all_resources = []
        for vpc in self.resources[
            "vpcs"
        ]:  # 像以上两个类的模板实例化的时候，也需要写成谁等于谁，只不过在这里是遍历赋值给了vpc
            all_resources.append(vpc.to_dict())

        for sg in self.resources["security_groups"]:
            all_resources.append(sg.to_dict())

        logger.debug(f"【云网络模拟器】获取所有模拟资源完成，共{len(all_resources)}个资源")
        return all_resources

    def get_resource_by_type(self, resource_type):
        """按类型获取资源"""
        # 新增：方法执行日志
        logger.info(f"【云网络模拟器】执行操作：按类型获取资源，资源类型：{resource_type}")
        if resource_type.lower() == "vpc":
            res_list = [vpc.to_dict() for vpc in self.resources["vpcs"]]
            logger.debug(f"【云网络模拟器】获取VPC类型资源完成，共{len(res_list)}个")
            return res_list
        elif resource_type.lower() == "securitygroup":
            res_list = [sg.to_dict() for sg in self.resources["security_groups"]]
            logger.debug(f"【云网络模拟器】获取安全组类型资源完成，共{len(res_list)}个")
            return res_list
        # 新增：不支持的资源类型警告日志
        logger.warning(f"【云网络模拟器】不支持的资源类型：{resource_type}，返回空列表")
        return []

    def simulate_creating_vpc(self, name, cidr, region):
        """模拟创建VPC"""
        # 新增：方法执行日志
        logger.info(f"【云网络模拟器】执行操作：模拟创建VPC，名称：{name}，网段：{cidr}，地域：{region}")
        new_vpc = CloudVPC(
            vpc_id=f"vpc-simulated-{datetime.now().strftime('%Y%m%d%H%M%S')}",  # 这里的datetime是用的此脚本的模块
            # strftime() 返回的是字符串
            name=name,
            cidr_block=cidr,
            region=region,
            status="Creating",
            create_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.resources["vpcs"].append(new_vpc)
        # 新增：创建成功日志
        logger.info(f"【云网络模拟器】模拟创建VPC成功，新VPC ID：{new_vpc.id}")
        return {
            "operation": "simulate_create_vpc",
            "status": "success",
            "message": "这是一个模拟操作，真实环境需调用云厂商API（如 boto3, huaweicloud-sdk）",
            "resource": new_vpc.to_dict(),
        }


# 全局实例
# cloud_simulator = CloudNetworkSimulator()

# 新增：本地测试代码（直接运行该脚本可验证，注释后不影响项目调用）
if __name__ == "__main__":
    cloud_simulator = CloudNetworkSimulator()
    logger.info("=" * 50 + " 云网络模拟器 本地测试开始 " + "=" * 50)
    # 1. 测试获取所有资源
    all_res = cloud_simulator.get_all_resources()
    # 2. 测试按类型获取VPC
    vpc_res = cloud_simulator.get_resource_by_type("vpc")
    # 3. 测试模拟创建VPC
    cloud_simulator.simulate_creating_vpc("测试模拟VPC", "172.16.0.0/12", "cn-hangzhou")
    logger.info("=" * 50 + " 云网络模拟器 本地测试结束 " + "=" * 50)
