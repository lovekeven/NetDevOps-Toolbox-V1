import os
import sys
from time import strftime
import yaml
from datetime import datetime  # 从这个模块里面引入一个核心类
from pathlib import Path  # 从这个模块里面引入一个核心类

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
from utils.log_setup import setup_logger

logger = setup_logger("modelsS", "models.log")
# 导入我写好的阿里云的客户端
# from core.cloud.real_providers.ali_client import AliyunCloudClient
# 这个在哪里用到就在那里导入

# 导入阿里云服务端异常，方便精准捕获
from aliyunsdkcore.acs_exception.exceptions import ServerException

# 导入数据库(实例)
from db.database import db_manager


# 定义一个父类
class NetworkResource:
    def __init__(self, resource_id, name, resource_type, status="unknown", last_check_time=None, create_time=None):
        self.id = resource_id
        self.name = name
        self.type = resource_type  # 如：'physical_device', 'cloud_vpc'
        self.status = status
        self.last_check_time = last_check_time
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

    def __init__(
        self,
        device_id,
        name,
        ip_address,
        vendor,
        check_status,
        up_interfaces,
        dowan_interface,
        total_interfaces,
        cpu_usage,
        memory_usage,
        reachable,
        version,
        **kwargs,
    ):
        super().__init__(device_id, name, resource_type="physical_device", **kwargs)
        # 1.这句话的本质是：调用父类（NetworkResource）的__init__方法，给父类的属性赋值 —— 不是 “继承函数”，是 “主动调用父类的
        # 初始化方法，让子类能复用父类的属性”！
        # 2.super()是 Python 的内置函数，作用是：获取当前子类对应的父类对象。
        # 3.调用父类的__init__方法，让父类帮我们初始化通用属性。

        self.ip_address = ip_address
        self.vendor = vendor
        self.check_status = check_status
        self.up_interfaces = up_interfaces
        self.down_interface = dowan_interface
        self.total_interfaces = total_interfaces
        self.cpu_usage = cpu_usage
        self.memory_usage = memory_usage
        self.reachable = reachable
        self.version = version

    def get_details(self):
        # 这里可以整合你health_check.py里的逻辑
        return f"物理设备 {self.name} ({self.ip_address}) - {self.vendor}"

    def to_dict(self):
        base_dict = super().to_dict()
        base_dict.update(
            {
                "ip_address": self.ip_address,
                "vendor": self.vendor,
                "check_status": self.check_status,
                "up_interface": self.up_interfaces,
                "down_interface": self.down_interface,
                "total_interface": self.total_interfaces,
                "cpu_usage": self.cpu_usage,
                "memory_usage": self.memory_usage,
                "reachable": self.reachable,
                "version": self.version,
            }
        )
        return base_dict

    def update(self, check_results):
        """
        用设备健康检查结果更新档案卡属性
        :param check_results: 检查结果字典（即check_single_device返回的results）
        """
        # 基础检查状态
        self.check_status = check_results.get("check_status", "未知")
        self.reachable = check_results.get("reachable", False)
        self.status = check_results.get("status", "unknown")  # 健康状态：healthy/degraded/failed
        # 时间字段（最后检查时间）
        self.last_check_time = check_results.get("check_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        # 硬件指标
        self.cpu_usage = check_results.get("CPU_usage", "N/A")
        self.memory_usage = check_results.get("memory_usage", "N/A")
        self.version = check_results.get("version", "未知")
        # 接口指标（注意字段映射）
        self.up_interfaces = check_results.get("up_interface", 0)
        self.down_interface = check_results.get("down_interface", 0)  # 已修正笔误
        self.total_interfaces = check_results.get("total_interface", 0)
        logger.info(f"设备[{self.name}]档案卡已更新为最新检查结果")
        update_dict = self.to_dict()  # 这里已经拿到的是最新的了
        db_manager.update_physical_card(update_dict)
        logger.info(f"已成功更新数据里的{self.name}数据")

    @classmethod
    # 定义一个类的方法，不用实例化直接可以用
    def dict_to_PhysicalDevice(cls, card_dict):
        # cls可以自定义，
        # cls()类的实例化
        return cls(
            device_id=card_dict.get("device_id"),
            name=card_dict.get("name"),
            ip_address=card_dict.get("ip_address"),
            vendor=card_dict.get("vendor", "未知厂商"),
            check_status=card_dict.get("check_status", "未知"),
            up_interfaces=card_dict.get("up_interfaces", "未知"),
            dowan_interface=card_dict.get("down_interface", "未知"),  # 保留你原来的笔误，避免报错
            total_interfaces=card_dict.get("total_interfaces", "未知"),
            cpu_usage=card_dict.get("cpu_usage", "N/A"),
            memory_usage=card_dict.get("memory_usage", "N/A"),
            reachable=card_dict.get("reachable", "未检测"),
            version=card_dict.get("version", "未知"),
            create_time=card_dict.get("create_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            last_check_time=card_dict.get("last_check_time", "未检查"),
            status=card_dict.get("status", "unknown"),
        )


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


config_path_physical = os.path.join(ROOT_DIR, "config", "nornir_inventory.yaml")


# 生成物理设备档案卡（适配扁平化设备清单：SW1-SW6为顶层键，嵌套connection_options/data）
def load_physical_devices(config_path_physical):
    device_cards = []
    config_file = Path(config_path_physical)
    # 检查配置文件是否存在
    if not config_file.exists():
        logger.warning("物理设备清单配置文件不存在：%s", config_path_physical)
        return device_cards
    try:
        with open(config_file, "r", encoding="utf-8") as f:

            device_data = yaml.safe_load(f) or {}

        for device_name, device_info in device_data.items():
            # 容错处理：防止配置字段缺失导致程序崩溃
            hostname = device_info.get("hostname", "")  # 设备IP/主机名
            vendor = device_info.get("data", {}).get("vendor", "未知厂商")  # 从data中取厂商
            # 可选：提取设备角色/位置（后续档案卡可扩展，暂时留用）
            # role = device_info.get("data", {}).get("role", "未知角色")
            # location = device_info.get("data", {}).get("location", "未知位置")

            # 跳过字段缺失的无效设备
            if not hostname:
                logger.warning("设备%s配置缺失hostname，跳过生成档案卡", device_name)
                continue

            # 实例化PhysicalDevice，生成档案卡（字段完全对齐新配置）
            dev_card = PhysicalDevice(
                device_id=device_name,  # 设备ID=设备名（SW1/SW2）
                name=device_name,  # 设备名
                ip_address=hostname,  # 核心改动：用hostname作为IP地址
                vendor=vendor,  # 核心改动：从data.vendor取厂商/设备类型
                create_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                check_status="未知",
                up_interfaces="未知",
                dowan_interface="未知",
                total_interfaces="未知",
                cpu_usage="N/A",
                memory_usage="N/A",
                reachable="未检测",
                version="未知",
            )
            device_cards.append(dev_card)
            logger.info(f"生成物理设备档案卡：{dev_card.get_details()}")

        # 生成完成日志（修正原错别字：答案卡→档案卡）
        logger.info(f"物理设备档案卡生成完成！共成功生成{len(device_cards)}个设备档案卡")
        return device_cards

    except yaml.YAMLError as e:
        # 单独捕获YAML解析错误，更精准
        logger.error(f"解析设备清单YAML文件失败：{str(e)[:200]}")
        return device_cards
    except Exception as e:
        # 捕获其他所有异常
        error_msg = str(e)
        logger.error(f"加载物理设备配置失败：{error_msg[:200]}")
        return device_cards


# 生成云资源档案卡
# 一：先获取真实云资源的密钥
def get_cloud_credentials(vendor="aliyun"):
    if vendor == "aliyun":
        # 环境变量名自定义，建议大写+云厂商标识，避免冲突
        ak = os.getenv("ALIYUN_AK")
        sk = os.getenv("ALIYUN_SK")
    else:
        ak, sk = None, None
    # 简单校验，打印日志（不打印密钥本身）
    if not ak or not sk:
        logger.error(f"未获取到{vendor}的密钥，请检查系统环境变量是否配置")
    return ak, sk


# 二：读取云资源的配置文件
config_path_cloud = os.path.join(ROOT_DIR, "config", "cloud_resources.yaml")


def load_cloud_resources():
    from core.cloud.real_providers.ali_client import AliyunCloudClient

    vpc_cards = []
    sg_cards = []
    config_file = Path(config_path_cloud)
    if not config_file.exists():
        logger.error(f"没找到云资源配置文件：{config_path_cloud}")
        return vpc_cards, sg_cards

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            cloud_config = yaml.safe_load(f) or {}

        # 先获取云平台通用配置（如默认地域）
        aliyun_common = cloud_config.get("cloud_common", {}).get("aliyun", {})
        default_region = aliyun_common.get("default_region", "cn-hangzhou")

        # 遍历VPC配置：区分real/sim
        vpcs_config = cloud_config.get("vpcs", {})
        for vpc_number, vpc_info in vpcs_config.items():
            resource_mode = vpc_info.get("resource_mode", "sim")
            cloud_vendor = vpc_info.get("cloud_vendor", "aliyun")
            region = vpc_info.get("region", default_region)  # 用配置地域，无则用默认
            vpc_name = vpc_info.get("name", vpc_number)
            vpc_id = vpc_info.get("vpc_id", "unknown")

            # 分支1：模拟资源（sim）→ 直接用配置文件字段
            if resource_mode == "sim":
                vpc_card = CloudVPC(
                    vpc_id=vpc_id,
                    name=vpc_name,
                    cidr_block=vpc_info.get("cidr_block", ""),
                    region=region,
                    subnets=vpc_info.get("subnets", []),
                    create_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    status="running",  # 模拟资源默认运行
                )
                vpc_cards.append(vpc_card)
                mode_tag = "【模拟】"
                logger.info(f"生成模拟VPC卡片并加入列表：{vpc_name}")

            # 分支2：真实资源（real）→ 先调API拉取真实信息，再生成档案卡
            else:
                # 1. 安全获取云厂商密钥（和客户端统一的AK/SK）

                ak, sk = get_cloud_credentials(cloud_vendor)
                if not ak or not sk:
                    logger.error(f"跳过【真实】VPC {vpc_id}：密钥获取失败")
                    continue
                try:
                    # 2. 实例化你写的阿里云客户端（传入AK/SK/地域，和配置一致）
                    aliyun_client = AliyunCloudClient(ak=ak, sk=sk, region=region)
                    # 3. 调用你写的get_vpcs()，直接获取真实CloudVPC实例列表
                    real_vpc_list = aliyun_client.get_vpcs()  # 返回值是列表元素是对象
                    # 4. 按yaml里的vpc_id过滤：只取配置中指定的那个真实VPC（精准匹配）
                    target_vpc = next((v for v in real_vpc_list if v.id == vpc_id), None)

                    if not target_vpc:
                        logger.error(f"跳过【真实】VPC {vpc_id}：阿里云未找到该VPC ID")
                        continue
                    # 5. 直接复用客户端返回的CloudVPC实例（不用手动创建，字段全对齐）
                    vpc_card = target_vpc
                    vpc_cards.append(vpc_card)
                    logger.info(f"成功调用{cloud_vendor}API拉取【真实】VPC {vpc_id} 信息，并加入列表")
                    mode_tag = "【真实】"
                except ServerException as e:
                    # 捕获阿里云服务端异常（和你客户端的异常一致）
                    logger.error(f"跳过【真实】VPC {vpc_id}：阿里云API调用失败 - {str(e)[:200]}")
                    continue
                except Exception as e:
                    # 捕获其他未知异常
                    logger.error(f"跳过【真实】VPC {vpc_id}：拉取失败 - {str(e)[:200]}")
                    continue
            # 统一打印日志
            logger.info(f"生成云VPC档案卡 {mode_tag}：{vpc_card.get_details()}")

        # 遍历安全组配置：和VPC完全相同的分支逻辑
        sgs_config = cloud_config.get("security_groups", {})
        for sg_number, sg_info in sgs_config.items():
            resource_mode = sg_info.get("resource_mode", "sim")
            cloud_vendor = sg_info.get("cloud_vendor", "aliyun")
            region = sg_info.get("region", default_region)
            sg_name = sg_info.get("name", sg_number)
            vpc_id = sg_info.get("vpc_id", "unknown")
            sg_id = sg_info.get("sg_id", "unknown")

            # 分支1：模拟资源（sim）→ 直接用配置字段
            if resource_mode == "sim":
                sg_card = CloudSecurityGroup(
                    sg_id=sg_id,
                    name=sg_name,
                    vpc_id=vpc_id,
                    ingress_rules=sg_info.get("ingress_rules", []),
                    egress_rules=sg_info.get("egress_rules", []),
                    create_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    status="running",
                )
                sg_cards.append(sg_card)
                mode_tag = "【模拟】"
                logger.info(f"生成模拟安全组卡片并加入列表：{sg_name}")

            # 分支2：真实资源（real）→ 调API拉取真实规则/状态
            else:
                # 1. 安全获取云厂商密钥（和客户端统一的AK/SK）
                ak, sk = get_cloud_credentials(cloud_vendor)
                if not ak or not sk:
                    logger.error(f"跳过【真实】安全组 {sg_id}：密钥获取失败")
                    continue
                try:
                    # 2. 实例化你写的阿里云客户端（传入AK/SK/地域，和配置一致）
                    aliyun_client = AliyunCloudClient(ak=ak, sk=sk, region=region)
                    # 3. 调用你写的get_all_security_groups()，直接获取真实CloudSecurityGroup实例列表
                    real_sg_list = aliyun_client.get_all_security_groups()
                    # 4. 按yaml里的sg_id过滤：只取配置中指定的那个真实安全组（精准匹配）
                    target_sg = next((sg for sg in real_sg_list if sg.id == sg_id), None)
                    if not target_sg:
                        logger.error(f"跳过【真实】安全组 {sg_id}：阿里云未找到该安全组 ID")
                        continue
                    # 5. 直接复用客户端返回的CloudSecurityGroup实例（不用手动创建，字段全对齐）
                    sg_card = target_sg
                    sg_cards.append(sg_card)
                    logger.info(f"成功调用{cloud_vendor}API拉取【真实】安全组 {sg_id} 信息，并加入列表")
                    mode_tag = "【真实】"
                except ServerException as e:
                    # 捕获阿里云服务端异常（和你客户端的异常一致）
                    logger.error(f"跳过【真实】安全组 {sg_id}：阿里云API调用失败 - {str(e)[:200]}")
                    continue
                except Exception as e:
                    # 捕获其他未知异常
                    logger.error(f"跳过【真实】安全组 {sg_id}：拉取失败 - {str(e)[:200]}")
                    continue
            # 统一打印日志
            logger.info(f"生成云安全组档案卡 {mode_tag}：{sg_card.get_details()}")
    except Exception as e:
        logger.error(f"加载云资源配置失败：{str(e)[:200]}")

    # 最终统计日志（加总数量，和物理设备加载逻辑对齐）
    logger.info(f"\n 云资源档案卡生成完成：{len(vpc_cards)}个VPC + {len(sg_cards)}个安全组")
    return vpc_cards, sg_cards


# 获取全局物理设备档案卡列表（对外提供统一入口）
GLOBAL_PHYSICAL_DEVICE_CARDS = None
# 延迟初始化，避免模块重复导入时重复执行


# 物理设备档案卡的全局变量
def get_global_physical_cards():
    global GLOBAL_PHYSICAL_DEVICE_CARDS
    # 声明他是一个全局变量接下来在这个函数里要操作的 GLOBAL_PHYSICAL_DEVICE_CARDS，不是我函数自己的局部变量，而是「公共客厅」里那个
    # 模块级的全局变量，我要改的是它的内容！
    if GLOBAL_PHYSICAL_DEVICE_CARDS is None:
        # 并不是调用一次这个方法就入库一次，但是服务器重启必会入库一次
        # 因为这里判断了他是None的情况下才会入库
        crad_list = db_manager.get_all_physical_cards()
        if crad_list:  # 现在这是一个列表元素是字典
            GLOBAL_PHYSICAL_DEVICE_CARDS = [PhysicalDevice.dict_to_PhysicalDevice(crad) for crad in crad_list]
            logger.info("服务器并不是首次启动，档案卡仍然是上次检查的设备状态")
            logger.info("服务器启动：从数据库提取档案卡（全局变量）成功！")
            # 现在这个也是个列表元素是对象
        else:
            GLOBAL_PHYSICAL_DEVICE_CARDS = load_physical_devices(config_path_physical)
            GLOBAL_PHYSICAL_DEVICE_CARDS_DICTS = [card.to_dict() for card in GLOBAL_PHYSICAL_DEVICE_CARDS]
            db_manager.batch_add_physical_cards(GLOBAL_PHYSICAL_DEVICE_CARDS_DICTS)
            logger.info("服务器首次启动：成功将档案卡插入数据库中")
    return GLOBAL_PHYSICAL_DEVICE_CARDS


# 全局变量GLOBAL_PHYSICAL_DEVICE_CARDS留着，因为匹配要用


if __name__ == "__main__":
    # 全局测试开始日志
    logger.info("=" * 50 + " 开始加载【全量网络资源档案卡】 " + "=" * 50)

    # ========== 第一步：加载物理设备档案卡片 ==========
    logger.info("\n📌 开始加载物理设备档案卡...")
    # 调用加载函数，传入物理设备配置路径（已在上方定义的config_path_physical）
    physical_cards = get_global_physical_cards()
    # 打印物理设备卡片详情
    logger.info(f"\n📋 物理设备卡片列表详情（共{len(physical_cards)}个）：")
    for index, dev in enumerate(physical_cards, 1):  # 索引从一开始
        logger.info(f"  [{index}] {dev.get_details()} | 状态：{dev.status} | 创建时间：{dev.create_time}")

    # ========== 第二步：加载云资源档案卡片（VPC+安全组） ==========
    logger.info("\n📌 开始加载云资源档案卡...")
    vpc_cards, sg_cards = load_cloud_resources()
    true_vpc = 0
    fake_vpc = 0
    true_sg = 0
    fake_sg = 0

    # 打印VPC卡片详情
    logger.info(f"\n📋 云VPC卡片列表详情（共{len(vpc_cards)}个）：")
    for index, vpc in enumerate(vpc_cards, 1):
        if vpc.status == "running":
            vpc_type = "【模拟】"
            fake_vpc += 1
            logger.info(
                f"  [{index}] {vpc_type} {vpc.get_details()} | 状态：{vpc.status} | 创建时间：{vpc.create_time}"
            )
        else:
            vpc_type = "【真实】"
            true_vpc += 1
            logger.info(
                f"  [{index}] {vpc_type} {vpc.get_details()} | 状态：{vpc.status} | 创建时间：{vpc.create_time}"
            )
        # vpc_type = (
        #     "【模拟】" if vpc.status == "running" else "【真实】"
        # )  # running是我们给模拟资源的「专属状态码」，真实云资源的状态池里根本没有这个值，
        # logger.info(f"  [{index}] {vpc_type} {vpc.get_details()} | 状态：{vpc.status} | 创建时间：{vpc.create_time}")

    # 打印安全组卡片详情
    logger.info(f"\n📋 云安全组卡片列表详情（共{len(sg_cards)}个）：")
    for index, sg in enumerate(sg_cards, 1):
        if sg.status == "running":
            sg_type = "【模拟】"
            fake_sg += 1
            logger.info(f"  [{index}] {sg_type} {sg.get_details()} | 状态：{sg.status} | 创建时间：{sg.create_time}")
        else:
            vpc_type = "【真实】"
            true_sg += 1
            logger.info(f"  [{index}] {sg_type} {sg.get_details()} | 状态：{sg.status} | 创建时间：{sg.create_time}")
        # sg_type = "【模拟】" if sg.status == "running" else "【真实】"
        # logger.info(f"  [{index}] {sg_type} {sg.get_details()} | 状态：{sg.status} | 创建时间：{sg.create_time}")

    # ========== 第三步：全量资源档案卡统计（物理+云资源） ==========
    total_physical = len(physical_cards)  # 物理设备总数
    total_cloud_vpc = len(vpc_cards)  # 云VPC总数
    total_cloud_sg = len(sg_cards)  # 云安全组总数
    total_all = total_physical + total_cloud_vpc + total_cloud_sg  # 全量档案卡总数

    # 打印总统计日志（醒目分隔）
    logger.info("\n" + "=" * 60)
    logger.info(f"🎉 全量网络资源档案卡加载完成！总统计：")
    logger.info(f"  🖥️  物理设备：{total_physical}个")
    logger.info(f"  ☁️  云VPC：{total_cloud_vpc}个（模拟{fake_vpc}个+真实{true_vpc}个）")
    logger.info(f"  🔒  云安全组：{total_cloud_sg}个（模拟{fake_sg}个+真实{true_sg}个）")
    logger.info(f"  📊  全量档案卡总数：{total_all}张")
    logger.info("=" * 60 + " 全量资源加载测试结束 " + "=" * 60)
