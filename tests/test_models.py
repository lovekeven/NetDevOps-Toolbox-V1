import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
from utils.models import NetworkResource, CloudSecurityGroup, CloudVPC, PhysicalDevice
import pytest


class TestNetworkResource:
    # 测试父类的基础属性
    def test_base_resource_creation(self):
        resource = NetworkResource(resource_id="test-001", name="测试资源", resource_type="test_type", status="active")
        assert resource.id == "test-001"
        assert resource.name == "测试资源"
        assert resource.type == "test_type"
        assert resource.status == "active"
        assert resource.last_check_time is None
        assert resource.create_time is None

    # 测试返回的字典是否键值对是否正确
    def test_to_dict_method(self):
        resource = NetworkResource(resource_id="test-002", name="测试资源2", resource_type="test_type")
        result = resource.to_dict()
        assert result["id"] == "test-002"
        assert result["name"] == "测试资源2"
        assert result["type"] == "test_type"
        assert result["status"] == "unknown"  # 默认值
        assert "last_check" in result
        assert "create_time" in result

    # 测试get_details，看子类是否实现，子类是必须实现的
    def test_get_details_not_implemented(self):
        resource = NetworkResource("test-003", "test", "type")
        with pytest.raises(NotImplementedError) as exc_info:
            resource.get_details()
        assert "子类必须实现此方法" in str(exc_info.value)


# 测试物理设备模型
class TestPhysicalDevice:
    # 测试物理设备创建
    def test_physical_device_creation(self):

        device = PhysicalDevice(
            device_id="SW-001", name="核心交换机", ip_address="192.168.1.1", vendor="Huawei", status="active"
        )

        assert device.id == "SW-001"
        assert device.name == "核心交换机"
        assert device.ip_address == "192.168.1.1"
        assert device.vendor == "Huawei"
        assert device.type == "physical_device"
        assert device.status == "active"

    # 测试获取详情
    def test_physical_device_get_details(self):
        device = PhysicalDevice(device_id="SW-002", name="接入交换机", ip_address="192.168.1.2", vendor="Cisco")

        details = device.get_details()
        assert "物理设备" in details
        assert "接入交换机" in details
        assert "192.168.1.2" in details
        assert "Cisco" in details

    # 测试物理设备转字典
    def test_physical_device_to_dict(self):
        device = PhysicalDevice(device_id="SW-003", name="测试设备", ip_address="10.0.0.1", vendor="H3C")
        result = device.to_dict()
        assert result["ip_address"] == "10.0.0.1"  # 检查特有字段
        assert result["vendor"] == "H3C"


# 测试云VPC模型
class TestCloudVPC:

    # 测试VPC创建
    def test_cloud_vpc_creation(self):
        vpc = CloudVPC(
            vpc_id="vpc-001",
            name="生产VPC",
            cidr_block="10.0.0.0/16",
            region="cn-east-1",
            subnets=["10.0.1.0/24", "10.0.2.0/24"],
            status="available",
        )

        assert vpc.id == "vpc-001"
        assert vpc.name == "生产VPC"
        assert vpc.cidr_block == "10.0.0.0/16"
        assert vpc.region == "cn-east-1"
        assert vpc.type == "cloud_vpc"
        assert len(vpc.subnets) == 2
        assert vpc.status == "available"

    def test_cloud_vpc_to_dict(self):
        """测试VPC转字典"""
        vpc = CloudVPC(vpc_id="vpc-002", name="测试VPC", cidr_block="192.168.0.0/16", region="cn-north-1")

        result = vpc.to_dict()

        # 检查父类字段
        assert result["id"] == "vpc-002"
        assert result["name"] == "测试VPC"
        assert result["type"] == "cloud_vpc"

        # 检查特有字段
        assert result["cidr"] == "192.168.0.0/16"
        assert result["region"] == "cn-north-1"
        assert result["subnet_count"] == 0
        assert "managed_by" in result
        assert result["resource_type"] == "cloud_vpc"


# 测试安全组模型
class TestCloudSecurityGroup:

    def test_security_group_creation(self):
        sg = CloudSecurityGroup(
            sg_id="sg-001",
            name="web-servers",
            vpc_id="vpc-001",
            ingress_rules=[{"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr": "0.0.0.0/0"}],
            egress_rules=[{"protocol": "all", "cidr": "0.0.0.0/0"}],
            status="active",
        )

        assert sg.id == "sg-001"
        assert sg.name == "web-servers"
        assert sg.vpc_id == "vpc-001"
        assert sg.type == "cloud_security_group"
        assert len(sg.ingress_rules) == 1
        assert len(sg.egress_rules) == 1
        assert sg.status == "active"

    # 测试安全组转字典
    def test_security_group_to_dict(self):
        sg = CloudSecurityGroup(sg_id="sg-002", name="db-servers", vpc_id="vpc-002", ingress_rules=[], egress_rules=[])
        result = sg.to_dict()
        assert result["id"] == "sg-002"
        assert result["name"] == "db-servers"
        assert result["vpc_id"] == "vpc-002"
        assert result["resource_type"] == "cloud_security_group"
        assert result["rule_count"] == 0
        assert "managed_by" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
