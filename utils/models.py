# 定义一个父类
class NetworkResource:
    def __init__(self, resource_id, name, resource_type, status="unknown", create_time=None):
        self.id = resource_id
        self.name = name
        self.type = resource_type  # 如：'physical_device', 'cloud_vpc'
        self.status = status
        self.last_check_time = None
        self.create_time = create_time

    def get_details(self):
        """获取资源详情（子类必须实现）"""
        raise NotImplementedError("子类必须实现此方法")

    # 1.子类实现了同名方法，调用时优先执行子类的；没实现才执行父类的；所以子类没有这个方法调用的就是父类的，一旦调用父类的就直接报错
    def to_dict(self):
        """转换为字典，用于API返回"""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "status": self.status,
            "last_check": self.last_check_time,
            "create_time": self.create_time,
        }


class PhysicalDevice(NetworkResource):
    """物理网络设备"""

    def __init__(self, device_id, name, ip_address, vendor, **kwargs):
        super().__init__(device_id, name, resource_type="physical_device", **kwargs)
        # 1.这句话的本质是：调用父类（NetworkResource）的__init__方法，给父类的属性赋值 —— 不是 “继承函数”，是 “主动调用父类的
        # 初始化方法，让子类能复用父类的属性”！
        # 2.super()是 Python 的内置函数，作用是：获取当前子类对应的父类对象。
        # 3.调用父类的__init__方法，让父类帮我们初始化通用属性。

        self.ip_address = ip_address
        self.vendor = vendor

    def get_details(self):
        # 这里可以整合你health_check.py里的逻辑
        return f"物理设备 {self.name} ({self.ip_address}) - {self.vendor}"

    def to_dict(self):
        base_dict = super().to_dict()
        base_dict.update({"ip_address": self.ip_address, "vendor": self.vendor})
        return base_dict


class CloudVPC(NetworkResource):
    """云VPC资源"""

    def __init__(self, vpc_id, name, cidr_block, region, subnets=None, **kwargs):
        super().__init__(vpc_id, name, resource_type="cloud_vpc", **kwargs)
        # 父类不认识的参数传过去就报错：你给CloudVPC传了subnets，这个参数被**kwargs打包传给父类NetworkResource，但父类的__ini
        # t__只认识resource_id/name/resource_type/status，根本不知道subnets是啥，所以直接报 “意外的关键字参数” 错误；
        # 1.vpc_id给不同的vpc封地授予不同的身份证号
        # 2.cidr_block就是「CIDR 格式的网段」= VPC 封闭的 IP 范围
        # 3.**kwargs万能收纳盒，可以穿状态等等
        # 4.super().__init__(vpc_id, name, resource_type="cloud_vpc", **kwargs) 里的所有参数，最终都传给了父类NetworkResource
        # 的__init__方法，由父类的__init__决定 “谁留用、谁忽略”—— 多余的参数如果父类没定义，会直接报错；符合父类参数的，会赋值给父类的属性。
        self.cidr_block = cidr_block
        self.region = region
        self.subnets = subnets if subnets is not None else []

    def get_details(self):
        # 这里可以整合你concept_simulator.py里的逻辑
        return f"云VPC {self.name} ({self.cidr_block}) - 区域: {self.region}"

    def to_dict(self):
        base_dict = super().to_dict()
        base_dict.update(
            {
                "resource_type": self.type,  # 或直接使用self.type
                "cidr": self.cidr_block,
                "region": self.region,
                "subnet_count": len(self.subnets),
                # 为了保持API兼容，可以加上resource_type
                "managed_by": "NetDevOps Platform",
            }
        )
        return base_dict


class CloudSecurityGroup(NetworkResource):
    """模拟云安全组资源（继承NetworkResource，统一模型）"""

    def __init__(self, sg_id, name, vpc_id, ingress_rules, egress_rules, **kwargs):
        # 调用父类初始化通用属性
        super().__init__(sg_id, name, resource_type="cloud_security_group", **kwargs)
        # 定义安全组专属属性
        self.vpc_id = vpc_id
        self.ingress_rules = ingress_rules
        self.egress_rules = egress_rules

    def get_details(self):
        return f"安全组 {self.name} (关联VPC: {self.vpc_id}) - 规则数: {len(self.ingress_rules)+len(self.egress_rules)}"

    def to_dict(self):
        # 复用父类的通用字段 + 叠加专属字段（和你原来的逻辑一致）
        base_dict = super().to_dict()
        base_dict.update(
            {
                "resource_type": self.type,
                "vpc_id": self.vpc_id,
                "rule_count": len(self.ingress_rules) + len(self.egress_rules),
                "managed_by": "NetDevOps Platform (Simulated)",
            }
        )
        return base_dict


if __name__ == "__main__":
    # 给SW1开一张档案卡
    sw1_card = PhysicalDevice(device_id="SW1", name="核心交换机", ip_address="192.168.1.1", vendor="华为")
    # 打印看看
    print(f"创建了档案卡: {sw1_card.name}")
    print(f"卡片信息: {sw1_card.to_dict()}")  # 假设你写了个to_dict方法
