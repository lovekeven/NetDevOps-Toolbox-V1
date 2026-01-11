import argparse
from typing import Optional, Dict, Any
import requests
from log_setup import setup_logger

logger = setup_logger("api_checker", "api_checker.log")

from retry_decorator import api_retry


# 第二步：先建立一个初始化客户的工厂
class APIclient:
    def __init__(self, base_url: str, token: Optional[str] = None):  # 因为token值不是必须要传的，不传的话就是None
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        logger.debug("客户初始化成功！")

    # 第三步：建立一个类的方法，目的是可以去发送GET请求
    @api_retry
    def get(self, endpoint: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"  # endpoint 这个字符串开头（最左侧）的所有 / 符号
        logger.info(f"正在发送GET请求：{url}....")
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            logger.debug(f"API请求成功！状态码是：{response.status_code}")
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"错误：API请求失败 {e}")
            raise


# 第四步：定义一个检查云端服务器的函数，返回值是布尔值
def check_cloud_server_status(api_client: APIclient, server_id: str) -> bool:
    logger.info(f"正在检查云端服务器，ID：{server_id}")
    data = api_client.get(f"/servers/{server_id}/status")
    if not data:
        logger.warning("无法获取服务器状态数据")
        return False
    status = data.get("status")
    is_healthy = status == "running"
    if is_healthy:
        logger.info(f"服务器 {server_id} 状态正常 ({status})")
    else:
        logger.warning(f"服务器 {server_id} 状态异常 ({status})")
    return is_healthy


# 第五步：定义一个检查设备的函数，返回值依旧是布尔值
def check_device_status(api_client: APIclient) -> bool:
    logger.info("开始检查网络设备状态")
    data = api_client.get("/")
    if not data:
        logger.error("无法获取网络设备信息")
        return False
    device_name = data.get("device_name", "未知设备")
    device_model = data.get("model", "未知型号")
    device_ip = data.get("mgmt_ip", "未知IP")
    logger.info(f"设备名称：{device_name}")
    logger.info(f"设备型号：{device_model}")
    logger.info(f"设备IP：{device_ip}")

    interfaces = data.get("interfaces", [])
    all_interfaces_up = True
    logger.info(f"正在分析该设备的{len(interfaces)}个接口")
    for interface in interfaces:
        if interface.get("status") == "up":
            logger.debug(f"接口{interface.get('name','未知接口')}状态正常！")
        else:
            logger.warning(f"接口{interface.get('name','未知接口')}状态异常！")
            all_interfaces_up = False
    if all_interfaces_up:
        logger.info("检查完毕！所有接口正常")
    else:
        logger.error("检查完毕！接口存在异常！")
    return all_interfaces_up


def main():
    # 第一步：创建一个命令行参数
    parse = argparse.ArgumentParser(
        description="调用API检查云服务器或者设备",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用试例：
            %(prog)s --type cloud --base-url http://api.cloud.com --target 123 --token abc123
            %(prog)s --type network --base-url .....
""",
    )
    parse.add_argument(
        "--type", required=True, choices=["cloud", "network"], help="检查云端服务器状态，或者设备接口等状态"
    )
    parse.add_argument("--base-url", required=True, help="指定云端服务器或者设备的基础url")
    parse.add_argument("--target", help="指定云端服务器的ID")
    parse.add_argument("--token", help="指定云端服务器或者设备的专属令牌！")
    args = parse.parse_args()
    client = APIclient(base_url=args.base_url, token=args.token)
    check_passed = False
    if args.type == "cloud":
        if not args.target:
            logger.error("未指定云端服务器的ID，--target")
            return
        check_passed = check_cloud_server_status(client, args.target)
    elif args.type == "network":
        check_passed = check_device_status(client)
    if check_passed:
        logger.info("API状态检查完成，结果正常")
    else:
        logger.error("API状态检查完成，发现异常")


if __name__ == "__main__":
    main()
