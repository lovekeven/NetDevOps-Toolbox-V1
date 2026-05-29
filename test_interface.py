import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from netmiko import ConnectHandler

# 设备信息
device = {
    "device_type": "hp_comware",
    "host": "192.168.56.11",
    "username": "admin",
    "password": "password",
}

try:
    print("连接设备...")
    conn = ConnectHandler(**device)
    print("连接成功！")
    
    print("\n=== 执行 display interface brief ===")
    output = conn.send_command_timing("display interface brief", delay_factor=3)
    print(f"输出长度: {len(output)}")
    print(f"输出内容:\n{output}")
    
    print("\n=== 按行显示 ===")
    for i, line in enumerate(output.split("\n")):
        print(f"行{i}: {repr(line)}")
    
    conn.disconnect()
    print("\n连接已断开")
except Exception as e:
    print(f"错误: {e}")
