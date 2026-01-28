import sys
import os
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
# 是为了我导入别人，现在看得到即使我想导入的函数跟我同级但是万一我在桌面运行这个脚本的话
# sys.path的列表里的索引0就不是这个脚本的上级目录了！
from core.health_check.health_checker import read_devices_yml


def test_read_devices_yml():
    yaml_connect = """
devices:
  test_sw1:
    device_type: hp_coware
    host: 10.0.0.1
    username: admin123
    password: password123
    port: 22
  test_sw2:
    device_type: cisco_ios
    host: 10.0.0.2
    username: admin456
    password: password456
    port: 22
    """
    devices = read_devices_yml(yaml_connect=yaml_connect)
    assert len(devices) == 2, f"测试失败:预期两个设备，实则{len(devices)}台设备！"
    required_keys = {"device_type", "host", "username", "password", "port"}
    for device in devices:
        assert all(key in device for key in required_keys), f"测试失败：{device.get('host','未知设备')}存在键的缺失"
    assert devices[0]["host"] == "10.0.0.1", f"测试失败：第一台设备的host应该是10.0.0.1,但得到{devices[0]['host']}！"
    assert (
        devices[1]["device_type"] == "cisco_ios"
    ), f"测试失败：第二台设备应该是cisco_ios，但得到{devices[1]['device_type']}！"
    print("测试test_read_devices_yml成功！")


def test_read_devices_yml_empty():
    yaml_connect = " "
    devices = read_devices_yml(yaml_connect=yaml_connect)
    assert devices == [], f"测试失败：当YAML的设备列表为空的时候，预期返回空列表，但得到了{devices}"
    print("测试read_devices_yml_empty成功！")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
    print("所有测试通过！")
