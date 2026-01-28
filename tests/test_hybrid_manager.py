import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
# 一，导入测试造假的模块
from unittest.mock import Mock

# 二，导入资源混合管理器脚本
from core.hybrid_manager.hybrid_manager import HybridResourceManager

# 三，导入测试模块框架
import pytest


# 测试混合资源管理器
class TestHybridResourceManager:
    # 测试使用模拟模式初始化
    def test_init_with_simulated_mode(self, mocker):  # pytest-mock(pytest 官方维护的插件)传了一个造假工具箱
        mocker.patch("core.hybrid_manager.hybrid_manager.NORNIR_AVAILABLE", False)
        mocker.patch("core.hybrid_manager.hybrid_manager.ALIYUN_AVAILABLE", False)
        mock_simulator = Mock()
        # 先创建了一个假对象
        # 这里的resourses不要写错因为在原脚本中是这样cloud_simulator = CloudNetworkSimulator()
        # vpc_resource = cloud_simulator.resources["vpcs"]
        # 现在这个实例化cloud_simulator这个变成了假对象，cloud_simulator.resources所以这个对象要对的上
        mock_simulator.resources = {
            "vpcs": [Mock(type="cloud_vpc", id="vpc-001")],
            "security_groups": [Mock(type="cloud_security_group", id="sg-001")],
        }
        mocker.patch("core.hybrid_manager.hybrid_manager.CloudNetworkSimulator", return_value=mock_simulator)
        # 如果这里只传mock_simulator的话，另一个脚本CloudNetworkSimulator()实例化的时候，就会是mock_simulator(),这样返回的还
        # 是什么都没有的假对象
        manager = HybridResourceManager(cloud_mode="simulated")
        assert manager.cloud_model == "simulated"
        assert len(manager.cloud_resources) == 2
        assert len(manager.all_resources) == 2

    # 测试获取所有资源
    def test_get_all_resources(self, mocker):
        manager = HybridResourceManager.__new__(HybridResourceManager)  # 先创建一个空的实例
        mock_phy = Mock(type="physical_device", id="SW-001")
        mock_vpc = Mock(type="cloud_vpc", id="vpc-001")
        resources = [mock_phy, mock_vpc]
        manager.all_resources = resources
        # 给我这个空实例的一个属性(属性不是瞎找的，是原来的类里面有的)，赋值
        result = manager.get_all_resources()
        # 只验证方法是否返回all_resources，和原脚本无关
        assert result == manager.all_resources
        assert len(result) == 2
        assert result[0].id == "SW-001"
        assert result[1].id == "vpc-001"

    # 测试按类型获取资源
    def test_get_resource_by_type(self, mocker):
        manager = HybridResourceManager.__new__(HybridResourceManager)
        mock_device = Mock()
        mock_device.type = "physical_device"
        mock_device.id = "SW-001"

        mock_vpc = Mock()
        mock_vpc.type = "cloud_vpc"
        mock_vpc.id = "vpc-001"

        mock_sg = Mock()
        mock_sg.type = "cloud_security_group"
        mock_sg.id = "sg-001"
        manager.all_resources = [mock_device, mock_vpc, mock_sg]
        physical_resources = manager.get_resource_by_type("physical_device")
        assert len(physical_resources) == 1
        assert physical_resources[0].type == "physical_device"

        cloud_resources = manager.get_resource_by_type("cloud_vpc")
        assert len(cloud_resources) == 1
        assert cloud_resources[0].type == "cloud_vpc"

    # 测试按ID获取资源"""
    def test_get_resource_by_id(self):
        manager = HybridResourceManager.__new__(HybridResourceManager)

        # 创建模拟资源
        mock_device = Mock()
        mock_device.id = "SW-001"
        mock_device.name = "Switch-01"

        mock_vpc = Mock()
        mock_vpc.id = "vpc-001"
        mock_vpc.name = "VPC-01"

        manager.all_resources = [mock_device, mock_vpc]

        # 测试查找
        found = manager.get_resource_by_id("vpc-001")
        assert found is not None  # 如果不是None就对
        assert found.id == "vpc-001"
        assert found.name == "VPC-01"

        # 测试未找到
        not_found = manager.get_resource_by_id("non-existent")
        assert not_found is None

    # 测试健康状态摘要"""
    def test_get_health_summary(self):
        manager = HybridResourceManager.__new__(HybridResourceManager)
        # 创建模拟资源
        mock_device1 = Mock()
        mock_device1.type = "physical_device"
        mock_device1.status = "active"

        mock_device2 = Mock()
        mock_device2.type = "physical_device"
        mock_device2.status = "down"

        mock_vpc = Mock()
        mock_vpc.type = "cloud_vpc"
        mock_vpc.status = "available"

        mock_sg = Mock()
        mock_sg.type = "cloud_security_group"
        mock_sg.status = "active"

        manager.all_resources = [mock_device1, mock_device2, mock_vpc, mock_sg]

        # 获取健康摘要
        summary = manager.get_health_summary()  # 这个函数返回的是一个字典

        # 验证统计
        assert summary["total"] == 4
        assert summary["healthy_resources"] == 3  # 3个健康（active/available）
        assert summary["health_percentage"] == 75.0

        # 验证类型统计
        assert summary["resource_types"]["physical_device"] == 2
        assert summary["resource_types"]["cloud_vpc"] == 1
        assert summary["resource_types"]["cloud_security_group"] == 1

        # 验证时间戳
        assert "last_check" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
