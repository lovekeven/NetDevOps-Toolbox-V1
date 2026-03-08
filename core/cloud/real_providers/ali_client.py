import json  # 阿里云返回的是二进制，转换为JSON格式的字符串后需要json模块的方法解析成字典
import sys
import os
from typing import List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(ROOT_DIR)
from utils.aliyun_time import convert_aliyun_time


try:
    from aliyunsdkcore.client import AcsClient
    from aliyunsdkcore.acs_exception.exceptions import ServerException
    from aliyunsdkvpc.request.v20160428.DescribeVpcsRequest import DescribeVpcsRequest
    from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest
    from aliyunsdkecs.request.v20140526.DescribeSecurityGroupsRequest import DescribeSecurityGroupsRequest
    ALIYUN_SDK_AVAILABLE = True
except ImportError:
    ALIYUN_SDK_AVAILABLE = False
    AcsClient = None
    ServerException = None
    DescribeVpcsRequest = None
    DescribeInstancesRequest = None
    DescribeSecurityGroupsRequest = None

from utils.models import CloudVPC, CloudSecurityGroup


class AliyunCloudClient:
    # 创建阿里云的一个综合大厅
    def __init__(self, ak: str = None, sk: str = None, region: str = "cn-hangzhou"):
        self.ak = ak or os.getenv("ALIYUN_AK")
        self.sk = sk or os.getenv("ALIYUN_SK")
        self.region = region
        if not ALIYUN_SDK_AVAILABLE:
            self.client = None
            return
        if not self.ak or not self.sk:
            raise ValueError("ALIYUN_AK and ALIYUN_SK must be set")
        self.client = AcsClient(self.ak, self.sk, self.region)

    def get_vpcs(self) -> List[CloudVPC]:
        try:
            request = DescribeVpcsRequest()
            request.set_accept_format("json")
            response = self.client.do_action_with_exception(request)
            # do_action_with_exception客户端提交的方法
            response_dict = json.loads(response.decode("utf-8"))
            vpcs = []
            for vpc in response_dict.get("Vpcs", {}).get("Vpc", []):
                create_time = convert_aliyun_time(vpc.get("CreationTime"))
                unified_vpc = CloudVPC(
                    vpc_id=vpc.get("VpcId"),  # 阿里云是VpcId
                    name=vpc.get("VpcName"),  # 阿里云是VpcName
                    cidr_block=vpc.get("CidrBlock"),  # 阿里云是CidrBlock
                    region=self.region,
                    status=vpc.get("Status").lower() if vpc.get("Status") else "available",
                    create_time=create_time,
                )
                vpcs.append(unified_vpc)

            return vpcs
        except ServerException as e:
            print(f"获取VPC列表失败: {e}")
            raise

    def get_all_security_groups(self) -> List[CloudSecurityGroup]:
        try:
            request = DescribeSecurityGroupsRequest()
            request.set_accept_format("json")
            response = self.client.do_action_with_exception(request)
            response_dict = json.loads(response.decode("utf-8"))
            # 1..decode("utf-8") —— 二进制转 UTF-8 字符串
            sgs = []
            for sg in response_dict.get("SecurityGroups", {}).get("SecurityGroup", []):
                create_time = convert_aliyun_time(sg.get("CreationTime"))
                # 阿里云：解析安全组规则（入方向/出方向，简化版）
                ingress_rules = []
                egress_rules = []
                # 4. 阿里云→统一模型：字段名适配（核心差异点）
                unified_sg = CloudSecurityGroup(
                    sg_id=sg.get("SecurityGroupId"),  # 阿里云：SecurityGroupId
                    name=sg.get("SecurityGroupName"),  # 阿里云：SecurityGroupName
                    vpc_id=sg.get("VpcId"),  # 阿里云：VpcId
                    ingress_rules=ingress_rules,  # 规则解析后续补
                    egress_rules=egress_rules,
                    status=(
                        sg.get("Status").lower() if sg.get("Status") else "active"
                    ),  # 阿里云Status：Available→转active
                    create_time=create_time,
                )
                sgs.append(unified_sg)

            return sgs

        except ServerException as e:
            print(f"获取安全组失败: {e}")
            raise

    def get_all_instances(self):
        try:
            request = DescribeInstancesRequest()
            request.set_accept_format("json")
            response = self.client.do_action_with_exception(request)
            response_dict = json.loads(response.decode("utf-8"))
            instances = []
            for instance in response_dict.get("Instances", {}).get("Instance", []):
                create_time = convert_aliyun_time(instance.get("CreationTime"))
                instances.append(
                    {
                        "instance_id": instance.get("InstanceId"),
                        "name": instance.get("InstanceName"),
                        "status": instance.get("Status").lower(),
                        "vpc_id": instance.get("VpcAttributes", {}).get("VpcId"),
                        "create_time": create_time,
                    }
                )
            return instances
        except ServerException as e:
            print(f"获取ECS实例失败: {e}")
            raise

    def get_all_resources(self):
        resource = []
        try:
            resource.extend(self.get_all_security_groups())
            resource.extend(self.get_vpcs())
            return resource
        except ServerException as e:
            error_msg = str(e)
            print(f"获取全部资源失败{error_msg[:100]}")
            raise


if __name__ == "__main__":
    client = AliyunCloudClient()
    try:
        vpc_recources = client.get_vpcs()
        print(f"共查询{len(vpc_recources)}个VPC")
        for vpc in vpc_recources:
            print(f"---VPC: {vpc.name}:网段{vpc.cidr_block}")
    except Exception as e:
        print(f"获取VPC列表失败: {e}")
    try:
        security_group_recources = client.get_all_security_groups()
        print(f"共查询{len(security_group_recources)}个安全组")
        for sg in security_group_recources:
            print(f"--安全组: {sg.name}:ID{sg.sg_id}   VPCID:{sg.vpc_id}")
    except Exception as e:
        print(f"获取安全组列表失败: {e}")
