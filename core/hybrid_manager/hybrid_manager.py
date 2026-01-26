# 一.导入os,sys模块求出根路径方便导入其他模块
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
# 二.导入日志器
from utils.log_setup import setup_logger

logger = setup_logger("hybrid_manager", "hybrid_manager.log")
# 三.导入物理设备，云VPC,云安全组，模板
from utils.models import PhysicalDevice, CloudVPC, CloudSecurityGroup, NetworkResource

# 四.导入云网络模拟器(类不是实例)
from core.cloud.concept_simulator import CloudNetworkSimulator

# 五.导入类型注解List,Any,Dict
from typing import Any, List, Dict

# 六.导入datetime模块，记录最后检查时间
from datetime import datetime

# 七.尝试导入实例化的函数，和Nornir框架配置清单错误的错误，因为这是加载物理设备
try:
    from nornir import InitNornir
    from nornir.core.exceptions import NornirNoValidInventoryError

    NORNIR_AVAILABLE = True  # 导入成功可以用
except ImportError as e:
    NORNIR_AVAILABLE = False
# .尝试导入阿里云的客户端，用来访问真实的VPC和安全组
try:
    from core.cloud.real_providers.ali_client import (
        AliyunCloudClient,
    )  # 这里引入的是一个类，应付多个阿里云账号，需要再次实例化

    ALIYUN_AVAILABLE = True
except ImportError as e:
    ALIYUN_AVAILABLE = False


# 定于一个混合资源管理器类
class HybridResourceManager:
    def __init__(self, cloud_mode="simulated"):
        self.cloud_model = cloud_mode
        self.physical_devices = []
        self.cloud_resources = []  # 这个不是模拟真实的都有只能有一个，看你选啥’
        self.all_resources = []  # 包含物理设备和云资源
        self._load_physical_devices()  # 加载物理设备
        self._load_cloud_resources()  # 加载/收集云资源
        self._build_unified_view()

    # 第一步：加载物理设备
    def _load_physical_devices(self):
        if NORNIR_AVAILABLE is False:
            logger.error("加载nornir物理清单失败! 请查看Nornir的安装")
        try:
            INVENTORY_PATH = os.path.join(ROOT_DIR, "config", "nornir_config.yaml")  # 注意这里是配置文件
            # 1.必须给config_file指定完整/相对路径,只给文件名的话，Nornir 只会在当前运行脚本的目录里找，找不到就报错
            nr = InitNornir(config_file=INVENTORY_PATH)
            logger.info("nr实例初始化成功!")
            for (
                device_name,
                host,
            ) in nr.inventory.hosts.items():  # nr.inventory.hosts是一个字典 键：设备名 值：设备信息Host对象
                physical = PhysicalDevice(
                    device_id=device_name,
                    name=device_name,
                    ip_address=host.hostname,
                    vendor=host.platform if hasattr(host, "platform") else "unknown",
                    status="active",  # 假设都是活跃的
                )
                self.physical_devices.append(physical)
            logger.info("加载nornir物理清单成功")
            logger.info(f"共从nornir框架加载{len(self.physical_devices)}台物理设备")
        except NornirNoValidInventoryError as e:
            logger.error(f"加载nornir物理清单失败!请检查nornir清单相关配置{e}")
        except Exception as e:
            logger.error(f"加载nornir物理清单失败!请检查nornir主配置文件或检查相关物理模板{e}")

    # 第二步：加载/收集云资源，注意并不是真实云资源和模拟云资源同时的，而是其中之一
    def _load_cloud_resources(self):
        if self.cloud_model == "real" and ALIYUN_AVAILABLE:
            ALIYUN_AK = os.getenv("ALIYUN_AK")
            ALIYUN_SK = os.getenv("ALIYUN_SK")
            ALIYUN_REGION_ID = os.getenv("ALIYUN_REGION_ID", "cn-hangzhou")
            if ALIYUN_AK and ALIYUN_SK:
                try:
                    client = AliyunCloudClient(ak=ALIYUN_AK, sk=ALIYUN_SK, region=ALIYUN_REGION_ID)
                    logger.info("阿里云客户端初始化成功!")
                    vpc_resource = client.get_vpcs()
                    security_groups = client.get_all_security_groups()
                    # 先不增加esc了
                    self.cloud_resources.extend(vpc_resource)
                    self.cloud_resources.extend(security_groups)
                    logger.info("收集真实云资源成功！")
                    logger.info(f"真实模式：收集VPC资源：{len(vpc_resource)}个  收集安全组：{len(security_groups)}个")
                except Exception as e:
                    logger.error(
                        f"真实模式：收集云资源失败，请查看APIKEY是否正确或者检查阿里云客户端实例是否出现错误{e}"
                    )
            else:
                logger.error("请检查APIKEY配置，将退回模拟模式")
                try:
                    self._load_simulated_cloud()
                except Exception as e:
                    logger.error(f"进入模拟模式失败{e}")
        else:
            logger.info("进入模拟模式")
            try:
                self._load_simulated_cloud()
            except Exception as e:
                logger.error(f"进入模拟模式失败{e}")

    # 第三步：加载模拟的云资源
    def _load_simulated_cloud(self):
        try:
            logger.info("模拟模式：正在收集模拟的云资源")
            cloud_simulator = CloudNetworkSimulator()
            vpc_resource = cloud_simulator.resources["vpcs"]  # 返回值是一个列表，元素是对象
            security_groups = cloud_simulator.resources["security_groups"]  # 返回值是一个列表，元素是对象
            self.cloud_resources.extend(vpc_resource)
            self.cloud_resources.extend(security_groups)
            logger.info("模拟模式：收集云资源成功！")
            logger.info(f"模拟模式：收集VPC资源：{len(vpc_resource)}个  收集安全组：{len(security_groups)}个")
        except Exception as e:
            logger.error(f"模拟模式：收集云资源失败,请查看相关配置{e}")

    # 第四步：构建统一资源视图
    def _build_unified_view(self):
        self.all_resources = []  # 先清空避免重复加载 这里是追加
        # 物理设备返回的是对象，真实：vpc返回的是对象，安全组返回的是对象 模拟：vpc和安全组返回的是对象
        self.all_resources.extend(self.physical_devices)
        self.all_resources.extend(self.cloud_resources)
        # 按类型统计
        stats = {}
        for resource in self.all_resources:
            stats[resource.type] = stats.get(resource.type, 0) + 1

        logger.info(f"混合资源统计{stats}")

    # 第五步获取所有资源
    def get_all_resources(self) -> List[NetworkResource]:
        return self.all_resources

    # 第六步：按类型获取资源
    def get_resource_by_type(self, resource_type: str) -> List[NetworkResource]:
        return [r for r in self.all_resources if r.type == resource_type]

    # 第七步：按ID获取资源 需求是找单个不用列表推导式
    def get_resource_by_id(self, resource_id: str) -> NetworkResource:
        for r in self.all_resources:
            if r.id == resource_id:
                return r
        return None

    # 第八步：获取健康状态摘要
    def get_health_summary(self) -> Dict[str, Any]:
        total = len(self.all_resources)
        healthy = sum(
            1 for r in self.all_resources if r.status.lower() in ["active", "available", "running"]
        )  # 在ali_client
        # 传参的时候已经变小写了
        return {
            "total": total,
            "healthy_resources": healthy,
            "health_percentage": round((healthy / total * 100) if total > 0 else 0, 2),
            "last_check": datetime.now().isoformat(),
            "resource_types": {
                rtype: len(self.get_resource_by_type(rtype)) for rtype in set(r.type for r in self.all_resources)
            },
        }


hybrid_manager = HybridResourceManager(cloud_mode="simulated")
