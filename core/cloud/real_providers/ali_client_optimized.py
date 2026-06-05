"""
优化版阿里云客户端
支持分页、安全组规则解析、ECS实例完整信息等
"""

import json
import sys
import os
from typing import List, Dict, Optional
from dataclasses import dataclass

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(ROOT_DIR)

from utils.aliyun_time import convert_aliyun_time
from utils.log_setup import setup_logger

logger = setup_logger("ali_client", "ali_client.log")

# ============================================================
# SDK 导入
# ============================================================

try:
    from aliyunsdkcore.client import AcsClient
    from aliyunsdkcore.acs_exception.exceptions import ServerException, ClientException
    from aliyunsdkvpc.request.v20160428.DescribeVpcsRequest import DescribeVpcsRequest
    from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest
    from aliyunsdkecs.request.v20140526.DescribeSecurityGroupsRequest import DescribeSecurityGroupsRequest
    from aliyunsdkecs.request.v20140526.DescribeSecurityGroupAttributeRequest import DescribeSecurityGroupAttributeRequest
    ALIYUN_SDK_AVAILABLE = True
except ImportError:
    ALIYUN_SDK_AVAILABLE = False
    AcsClient = None
    ServerException = None
    ClientException = None
    DescribeVpcsRequest = None
    DescribeInstancesRequest = None
    DescribeSecurityGroupsRequest = None
    DescribeSecurityGroupAttributeRequest = None

from utils.models import CloudVPC, CloudSecurityGroup


# ============================================================
# 数据模型
# ============================================================

@dataclass
class SecurityGroupRule:
    """安全组规则"""
    direction: str  # ingress/egress
    protocol: str   # tcp/udp/icmp/all
    port_range: str # 1/65535
    source: str     # 0.0.0.0/0
    dest: str       # 0.0.0.0/0
    policy: str     # accept/drop
    priority: int   # 1-100
    description: str


@dataclass
class ECSInstance:
    """ECS实例"""
    instance_id: str
    instance_name: str
    status: str  # Running/Stopped/etc
    instance_type: str
    cpu: int
    memory: int  # MB
    public_ip: str
    private_ip: str
    os_type: str
    region: str
    create_time: str
    security_group_ids: List[str]
    vpc_id: str
    vswitch_id: str


# ============================================================
# 阿里云客户端
# ============================================================

class AliyunCloudClient:
    """阿里云客户端，支持分页、安全组规则解析等"""

    def __init__(self, ak: str = None, sk: str = None, region: str = "cn-hangzhou"):
        """
        初始化阿里云客户端

        Args:
            ak: Access Key ID
            sk: Access Key Secret
            region: 地域ID
        """
        self.ak = ak or os.getenv("ALIYUN_AK")
        self.sk = sk or os.getenv("ALIYUN_SK")
        self.region = region

        if not ALIYUN_SDK_AVAILABLE:
            logger.warning("阿里云 SDK 未安装，请安装: pip install aliyun-python-sdk-core aliyun-python-sdk-vpc aliyun-python-sdk-ecs")
            self.client = None
            return

        if not self.ak or not self.sk:
            logger.warning("阿里云凭证未配置，请设置环境变量 ALIYUN_AK 和 ALIYUN_SK")
            self.client = None
            return

        self.client = AcsClient(self.ak, self.sk, self.region)
        logger.info(f"阿里云客户端初始化成功，地域: {region}")

    def is_available(self) -> bool:
        """检查客户端是否可用"""
        return self.client is not None

    # ============================================================
    # VPC 管理
    # ============================================================

    def get_vpcs(self, page_size: int = 50) -> List[CloudVPC]:
        """
        获取VPC列表（支持分页）

        Args:
            page_size: 每页数量

        Returns:
            VPC列表
        """
        if not self.is_available():
            return []

        try:
            vpcs = []
            page_number = 1

            while True:
                request = DescribeVpcsRequest()
                request.set_accept_format("json")
                request.set_PageSize(page_size)
                request.set_PageNumber(page_number)

                response = self.client.do_action_with_exception(request)
                response_dict = json.loads(response.decode("utf-8"))

                vpc_list = response_dict.get("Vpcs", {}).get("Vpc", [])
                if not vpc_list:
                    break

                for vpc in vpc_list:
                    create_time = convert_aliyun_time(vpc.get("CreationTime"))
                    unified_vpc = CloudVPC(
                        vpc_id=vpc.get("VpcId"),
                        name=vpc.get("VpcName"),
                        cidr_block=vpc.get("CidrBlock"),
                        region=self.region,
                        status=vpc.get("Status").lower() if vpc.get("Status") else "available",
                        create_time=create_time,
                    )
                    vpcs.append(unified_vpc)

                # 检查是否还有下一页
                total_count = response_dict.get("TotalCount", 0)
                if page_number * page_size >= total_count:
                    break

                page_number += 1

            logger.info(f"获取VPC列表成功，共 {len(vpcs)} 个")
            return vpcs

        except ServerException as e:
            logger.error(f"获取VPC列表失败: {e}")
            raise
        except Exception as e:
            logger.error(f"获取VPC列表异常: {e}")
            raise

    # ============================================================
    # 安全组管理
    # ============================================================

    def get_all_security_groups(self, page_size: int = 50) -> List[CloudSecurityGroup]:
        """
        获取安全组列表（支持分页）

        Args:
            page_size: 每页数量

        Returns:
            安全组列表
        """
        if not self.is_available():
            return []

        try:
            sgs = []
            page_number = 1

            while True:
                request = DescribeSecurityGroupsRequest()
                request.set_accept_format("json")
                request.set_PageSize(page_size)
                request.set_PageNumber(page_number)

                response = self.client.do_action_with_exception(request)
                response_dict = json.loads(response.decode("utf-8"))

                sg_list = response_dict.get("SecurityGroups", {}).get("SecurityGroup", [])
                if not sg_list:
                    break

                for sg in sg_list:
                    create_time = convert_aliyun_time(sg.get("CreationTime"))

                    # 获取安全组规则
                    ingress_rules, egress_rules = self._get_security_group_rules(
                        sg.get("SecurityGroupId")
                    )

                    unified_sg = CloudSecurityGroup(
                        sg_id=sg.get("SecurityGroupId"),
                        name=sg.get("SecurityGroupName"),
                        vpc_id=sg.get("VpcId"),
                        ingress_rules=ingress_rules,
                        egress_rules=egress_rules,
                        status=sg.get("Status").lower() if sg.get("Status") else "active",
                        create_time=create_time,
                    )
                    sgs.append(unified_sg)

                # 检查是否还有下一页
                total_count = response_dict.get("TotalCount", 0)
                if page_number * page_size >= total_count:
                    break

                page_number += 1

            logger.info(f"获取安全组列表成功，共 {len(sgs)} 个")
            return sgs

        except ServerException as e:
            logger.error(f"获取安全组列表失败: {e}")
            raise
        except Exception as e:
            logger.error(f"获取安全组列表异常: {e}")
            raise

    def _get_security_group_rules(self, security_group_id: str) -> tuple:
        """
        获取安全组规则

        Args:
            security_group_id: 安全组ID

        Returns:
            (入站规则列表, 出站规则列表)
        """
        ingress_rules = []
        egress_rules = []

        try:
            # 获取入站规则
            request = DescribeSecurityGroupAttributeRequest()
            request.set_accept_format("json")
            request.set_SecurityGroupId(security_group_id)
            request.set_Direction("ingress")

            response = self.client.do_action_with_exception(request)
            response_dict = json.loads(response.decode("utf-8"))

            for rule in response_dict.get("Permissions", {}).get("Permission", []):
                ingress_rules.append(SecurityGroupRule(
                    direction="ingress",
                    protocol=rule.get("IpProtocol", "all"),
                    port_range=rule.get("PortRange", "-1/-1"),
                    source=rule.get("SourceCidrIp", ""),
                    dest="",
                    policy=rule.get("Policy", "accept"),
                    priority=int(rule.get("Priority", 1)),
                    description=rule.get("Description", "")
                ))

            # 获取出站规则
            request = DescribeSecurityGroupAttributeRequest()
            request.set_accept_format("json")
            request.set_SecurityGroupId(security_group_id)
            request.set_Direction("egress")

            response = self.client.do_action_with_exception(request)
            response_dict = json.loads(response.decode("utf-8"))

            for rule in response_dict.get("Permissions", {}).get("Permission", []):
                egress_rules.append(SecurityGroupRule(
                    direction="egress",
                    protocol=rule.get("IpProtocol", "all"),
                    port_range=rule.get("PortRange", "-1/-1"),
                    source="",
                    dest=rule.get("DestCidrIp", ""),
                    policy=rule.get("Policy", "accept"),
                    priority=int(rule.get("Priority", 1)),
                    description=rule.get("Description", "")
                ))

        except Exception as e:
            logger.warning(f"获取安全组 {security_group_id} 规则失败: {e}")

        return ingress_rules, egress_rules

    # ============================================================
    # ECS 管理
    # ============================================================

    def get_all_instances(self, page_size: int = 50) -> List[ECSInstance]:
        """
        获取ECS实例列表（支持分页）

        Args:
            page_size: 每页数量

        Returns:
            ECS实例列表
        """
        if not self.is_available():
            return []

        try:
            instances = []
            page_number = 1

            while True:
                request = DescribeInstancesRequest()
                request.set_accept_format("json")
                request.set_PageSize(page_size)
                request.set_PageNumber(page_number)

                response = self.client.do_action_with_exception(request)
                response_dict = json.loads(response.decode("utf-8"))

                instance_list = response_dict.get("Instances", {}).get("Instance", [])
                if not instance_list:
                    break

                for instance in instance_list:
                    # 获取公网IP
                    public_ip = ""
                    if instance.get("PublicIpAddress", {}).get("IpAddress"):
                        public_ip = instance["PublicIpAddress"]["IpAddress"][0]

                    # 获取私网IP
                    private_ip = ""
                    if instance.get("VpcAttributes", {}).get("PrivateIpAddress", {}).get("IpAddress"):
                        private_ip = instance["VpcAttributes"]["PrivateIpAddress"]["IpAddress"][0]

                    # 获取安全组ID
                    security_group_ids = instance.get("SecurityGroupIds", {}).get("SecurityGroupId", [])

                    create_time = convert_aliyun_time(instance.get("CreationTime"))

                    ecs_instance = ECSInstance(
                        instance_id=instance.get("InstanceId", ""),
                        instance_name=instance.get("InstanceName", ""),
                        status=instance.get("Status", "Unknown"),
                        instance_type=instance.get("InstanceType", ""),
                        cpu=instance.get("Cpu", 0),
                        memory=instance.get("Memory", 0),
                        public_ip=public_ip,
                        private_ip=private_ip,
                        os_type=instance.get("OSType", ""),
                        region=self.region,
                        create_time=create_time,
                        security_group_ids=security_group_ids,
                        vpc_id=instance.get("VpcAttributes", {}).get("VpcId", ""),
                        vswitch_id=instance.get("VpcAttributes", {}).get("VSwitchId", "")
                    )
                    instances.append(ecs_instance)

                # 检查是否还有下一页
                total_count = response_dict.get("TotalCount", 0)
                if page_number * page_size >= total_count:
                    break

                page_number += 1

            logger.info(f"获取ECS实例列表成功，共 {len(instances)} 个")
            return instances

        except ServerException as e:
            logger.error(f"获取ECS实例列表失败: {e}")
            raise
        except Exception as e:
            logger.error(f"获取ECS实例列表异常: {e}")
            raise

    # ============================================================
    # 综合查询
    # ============================================================

    def get_all_resources(self) -> Dict:
        """
        获取所有资源（VPC + 安全组 + ECS）

        Returns:
            资源字典
        """
        resources = {
            "vpcs": [],
            "security_groups": [],
            "instances": [],
            "summary": {
                "vpc_count": 0,
                "sg_count": 0,
                "instance_count": 0,
                "running_instances": 0,
                "stopped_instances": 0
            }
        }

        try:
            # 获取VPC
            resources["vpcs"] = self.get_vpcs()
            resources["summary"]["vpc_count"] = len(resources["vpcs"])

            # 获取安全组
            resources["security_groups"] = self.get_all_security_groups()
            resources["summary"]["sg_count"] = len(resources["security_groups"])

            # 获取ECS实例
            resources["instances"] = self.get_all_instances()
            resources["summary"]["instance_count"] = len(resources["instances"])

            # 统计实例状态
            for instance in resources["instances"]:
                if instance.status.lower() == "running":
                    resources["summary"]["running_instances"] += 1
                else:
                    resources["summary"]["stopped_instances"] += 1

            logger.info(f"获取所有资源成功: VPC={resources['summary']['vpc_count']}, "
                       f"安全组={resources['summary']['sg_count']}, "
                       f"ECS={resources['summary']['instance_count']}")

        except Exception as e:
            logger.error(f"获取所有资源失败: {e}")
            raise

        return resources

    # ============================================================
    # 资源统计
    # ============================================================

    def get_resource_summary(self) -> Dict:
        """
        获取资源统计摘要

        Returns:
            统计摘要字典
        """
        try:
            resources = self.get_all_resources()
            return resources["summary"]
        except Exception as e:
            logger.error(f"获取资源统计失败: {e}")
            return {
                "vpc_count": 0,
                "sg_count": 0,
                "instance_count": 0,
                "running_instances": 0,
                "stopped_instances": 0,
                "error": str(e)
            }


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    # 测试客户端
    client = AliyunCloudClient()

    if client.is_available():
        print("阿里云客户端可用")

        # 获取资源统计
        summary = client.get_resource_summary()
        print(f"资源统计: {summary}")

        # 获取所有资源
        resources = client.get_all_resources()
        print(f"VPC数量: {resources['summary']['vpc_count']}")
        print(f"安全组数量: {resources['summary']['sg_count']}")
        print(f"ECS实例数量: {resources['summary']['instance_count']}")
    else:
        print("阿里云客户端不可用，请配置凭证")
