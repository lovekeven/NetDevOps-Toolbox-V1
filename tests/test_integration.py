# 文件路径：tests/test_cloud_resource.py
import os
import sys

# 配置路径（保证能导入core模块）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

# 导入需要测试的模块
from core.cloud.concept_simulator import cloud_simulator
from utils import NetworkResource


# ========== 必须以test_开头的测试函数 ==========
def test_unified_model_integration():
    """测试统一模型整合：资源数量+统一字段"""
    # 核心测试逻辑
    resources = cloud_simulator.get_all_resources()

    # 断言1：资源总数是3个（2个VPC+1个安全组）
    assert len(resources) == 3, f"预期3个资源，实际获取到{len(resources)}个"

    # 断言2：每个资源都有统一字段
    required_fields = ["name", "status", "resource_type"]
    for res in resources:
        for field in required_fields:
            assert field in res, f"资源{res['name']}缺失统一字段：{field}"


def test_vpc_type_check():
    """测试VPC类型检查：继承关系+方法存在"""
    vpcs = cloud_simulator.resources["vpcs"]

    for vpc in vpcs:
        # 断言1：是CloudVPC类型
        assert type(vpc).__name__ == "CloudVPC", f"VPC{vpc.name}类型错误"
        # 断言2：继承了NetworkResource
        assert isinstance(vpc, NetworkResource), f"VPC{vpc.name}不是NetworkResource子类"
        # 断言3：有to_dict方法
        assert hasattr(vpc, "to_dict"), f"VPC{vpc.name}缺失to_dict方法"


# import os
# import sys

# ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.path.append(ROOT_DIR)
# from core.cloud.concept_simulator import cloud_simulator
# from core.cloud.models import NetworkResource  # 1.唯一目的就是给isinstance(vpc, NetworkResource)用的！


# def test_unified_model_integration():
#     print("=== 测试统一模型整合 ===")
#     resources = cloud_simulator.get_all_resources()
#     print(f"获取到 {len(resources)} 个资源：")
#     for res in resources:
#         print(f"  - {res['name']} ({res.get('resource_type', res['type'])},{res['status']}) ")


# def test_vpc_type_check():
#     print("\\n=== 测试类型检查 ===")
#     vpcs = cloud_simulator.resources["vpcs"]  # 得出来的结果列表元素是CloudVPC 对象（不是字典）；
#     for vpc in vpcs:
#         print(f"VPC {vpc.name}: {type(vpc)}")
#         print(f"  是NetworkResource子类: {isinstance(vpc, NetworkResource)}")  # isinstance返回值true和flase
#         print(f"  to_dict结果: {vpc.to_dict()}")  # 1.vpc.to_dict() → 把 CloudVPC 对象转成字典；
