# NetDevOps-Toolbox-V1
## 一，项目描述
这是一款基于 Python 开发的网络设备自动化运维工具，能批量完成网络设备的配置备份和健康状态检查（接口、CPU、内存），通过统一调度中心简化操作，解决传统手动运维效率低、易出错的问题。
## 二，功能特性
- 自动化备份：支持批量备份指定/所有设备的接口配置，文件按IP+时间戳归档
- 健康检查：自动统计设备接口UP/DOWN数量、CPU使用率、内存使用率
- 统一调度：通过main.py一键切换备份/检查模式，操作简单
- 异常提示：连接失败时精准提示原因（认证失败、超时、IP不可达等）
- 配置灵活：设备信息通过YAML文件管理，新增设备无需改代码
## 三，技术栈
- 核心语言：Python 3.8+
- 网络设备连接：Netmiko
- 配置文件解析：PyYAML
- 命令行参数：argparse
## 四，安装与使用

### 1. 克隆项目
git clone https://github.com/lovekeven/NetDevOps-Toolbox-V1.git
cd NetDevOps-Toolbox-V1


### 2. 环境依赖安装
pip install netmiko>=4.0.0 pyyaml>=6.0
### 3. 设备配置文件编写

在项目根目录创建的 devices.yaml 文件里，按以下格式填写设备信息（示例）：
- devices:
  - switch1:
    - device_type: huawei  # 设备类型（华为设备填 huawei，华三填 hp_comware，具体参考 Netmiko 文档）
    - host: 192.168.91.111  # 设备 IP 地址
    - username: admin  # 登录用户名
    - password: Admin@123  # 登录密码
  - switch2:
    - device_type: huawei
    - host: 192.168.91.112
    - username: admin
    - password: Admin@123
  - router1:
    - device_type: huawei
    - host: 192.168.91.113
    - username: admin
    - password: Admin@123

注意：device_type 需根据实际设备厂商填写，确保与 Netmiko 支持的类型匹配，否则会导致连接失败。

### 4. 核心命令示例

通过 main.py 统一调度，支持两种模式（backup/检查），两种目标选择（--all/--ip），具体示例如下：
- 模式 1：备份功能
        备份所有设备配置：
        python main.py --mode backup --all

        备份指定 IP 的设备（支持多个 IP，空格分隔）：
        python main.py --mode backup --ip 192.168.91.111 192.168.91.112
        备份文件位置：项目根目录的 backupN1 文件夹，文件名格式为 设备IP__配置__年月日-时分秒.txt。


- 模式 2：健康检查功能
        检查所有设备健康状态：
        python main.py --mode check --all

        检查指定 IP 的设备健康状态（支持多个 IP，空格分隔）：
        python main.py --mode check --ip 192.168.91.112 192.168.91.113
        检查报告位置：项目根目录的 health_check_report.txt，包含各设备的接口状态、CPU/内存使用率、异常信息。

查看帮助文档：
        如需查看命令参数说明，执行：
        python main.py --help



## 五，项目结构

  - NetDevOps-Toolbox-V1/ # 项目根目录
  - ├── main.py # 统一调度中心（核心入口）
  - ├── backup.py # 备份功能核心脚本
  - ├── health_check.py # 健康检查功能核心脚本
  - ├── devices.yaml # 设备信息配置文件（需用户自行编写）
  - ├── README.md # 项目说明文档（本文件）
  - ├── LICENSE # 开源许可证（MIT）
  - ├── log_setup.py #创建日志配置模块
  - ├── test_device_reader.py #测试函数脚本
  - ├── api_checker.py #API模块，可以查询云端服务器和设备
  - ├── retry_decorator.py #装饰器模块
  - ├── PROJECT_JOURNEY.md #王建壮的网络工具箱项目演技和优化的日志
  - ├── backupN1/ # 备份文件归档目录（自动生成）
  - ├ ├── 192.168.91.111__配置__20240520-143025.txt
  - ├ └── 192.168.91.112__配置__20240520-143030.txt
  - ├── logs/ #日志文件归档目录（自动生成）
  - ├ ├── backup.log
  - ├ └── health_check.log
  - └── health_check_report.txt # 健康检查报告（自动生成）


### 致谢

这是我的第一个 NetDevOps 项目，感谢王建壮也就是我自己哈哈，让我逐步掌握 Python 自动化运维在网络领域的应用，脚本可能有点简陋，
以后的王建壮你要改改哈！这才是版本一 2026.1.1



