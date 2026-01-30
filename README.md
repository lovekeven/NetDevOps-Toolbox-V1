# NetDevOps-Toolbox-V1
## ✨ 最新进展：项目已升级为智能数据化系统（V7.0）！
- **日期**：2026年1月30日
- **里程碑**：成功构建云网络概念平台，混合云资源管理器，物理设备的健康检查档案卡
- **核心功能**：
    - 🗃️ **数据持久化**：集成SQLite数据库，扩展系统指标数据表，实现设备/系统/服务数据全量存储与追溯。
    - 🤖 **AI智能分析**：接入大模型API，可根据历史数据+实时监控指标自动生成智能运维报告。
    - ⚡ **专业并发框架**：优化Nornir框架逻辑，新增基于CPU/内存阈值的设备健康状态智能判定。
    - 📈 **系统可观测性**：完成全维度监控体系建设（系统级指标/API服务/Nornir框架/Web仪表盘），支持实时状态查询与阈值告警。
    - 🌐 **API能力扩展**：主要新增3个API接口，获取模拟云资源和真实云资源，混合资源管理页面，和一键查看物理设备的档案卡
- **技术栈**：Python, Flask, SQLite, Nornir, Netmiko, AI API, RESTful API, psutil（系统监控）
- **体验地址**：克隆项目后运行 `python web/web_dashboard.py`，即可在浏览器访问 `http://localhost:8080`（点击「检查系统服务状态」体验监控功能）
## 一，项目描述
这是一款基于 Python 开发的网络设备自动化运维工具，能批量完成网络设备的配置备份和健康状态检查（接口、CPU、内存），通过统一调度中心简化操作，解决传统手动运维效率低、易出错的问题。现在已升级
在保留原来的命令行功能，新增前后端分离的Web仪表盘，可通过Web界面直接触发设备配置备份。
## 二，功能特性
- 自动化备份：支持批量备份指定/所有设备的接口配置，文件按IP+时间戳归档
- 健康检查：自动统计设备接口UP/DOWN数量、CPU使用率、内存使用率
- 统一调度：通过main.py一键切换备份/检查模式，操作简单
- 异常提示：连接失败时精准提示原因（认证失败、超时、IP不可达等）
- 配置灵活：设备信息通过YAML文件管理，新增设备无需改代码
- （新增）Web界面直接触发设备: 点击按钮实时触发后端,进行设备检查或者备份
## 三，技术栈
- 核心语言：Python 3.8+
- 网络设备连接：Netmiko
- 配置文件解析：PyYAML
- 命令行参数：argparse
- 后端服务器搭建：flask
- 发送API请求：requests
## 四，安装与使用

### 1. 克隆项目
git clone https://github.com/lovekeven/NetDevOps-Toolbox-V1.git
cd NetDevOps-Toolbox-V1


### 2. 环境部署方式（二选一，按需选择）
> 说明：两种部署方式均可实现项目运行，无需同时操作，按需挑选即可。

#### 方式一：本地Python环境部署（适合开发者/需修改代码的用户）
1.  前提准备：已安装Python 3.8+（推荐3.9~3.11版本，兼容性更好）；
2.  打开终端/命令行工具，切换到项目根目录（包含`requirements.txt`文件）：
    ```bash
    # Windows示例（替换为你的项目实际路径）
    cd D:\Projects\NetDevOps-Toolbox-V1
    # Mac/Linux示例（替换为你的项目实际路径）
    cd ~/Projects/NetDevOps-Toolbox-V1
3.  pip install -r requirements.txt
#### 方式二：Docker 容器化部署（推荐新手 / 快速启动 / 无需配置 Python 环境）
1.  前提准备：本地已安装「Docker Desktop」（Windows/Mac）或「Docker Engine」（Linux），且 Docker 服务已启动；
2.  无需手动安装 Python / 项目依赖：Docker 会通过项目根目录的「Dockerfile」自动构建环境、安装所有依赖；
3.  打开终端 / 命令行工具，切换到项目根目录（包含Dockerfile文件）：
    ```bash
    # Windows示例（替换为你的项目实际路径）
    cd D:\Projects\NetDevOps-Toolbox-V1
    # Mac/Linux示例（替换为你的项目实际路径）
    cd ~/Projects/NetDevOps-Toolbox-V1
    构建 Docker 镜像（镜像名可自定义，建议与项目名一致）：
    docker build -t netdevops-toolbox:v1 .
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

#### 方式一：优先推荐 - Web仪表盘图形化操作（本地/Docker部署均支持，最简单）
Web仪表盘是目前最便捷的使用方式，两种部署方式启动后，操作步骤完全一致，无需输入任何命令。

##### 步骤1：根据你的部署方式，启动Web服务
1.  若为「本地Python环境部署」：
    ```
    项目根目录终端执行，启动Web仪表盘（核心脚本：web_dashboard.py）
    python web_dashboard.py
2.  若为「Docker 容器化部署」：
    ```
    启动容器后，Web仪表盘会自动运行（无需额外命令，已配置web_dashboard.py为入口）
    docker run -p 8080:8080 netdevops-toolbox:v1
##### 步骤 2：访问 Web 仪表盘，完成操作
1.  打开浏览器，输入访问地址：http://127.0.0.1:5000；
2.  进入页面后，可直观看到所有设备列表；
3.  执行「设备备份」：点击对应设备后的「备份」按钮，等待操作完成（页面会实时显示「备份中→备份成功」反馈）
4.  执行「健康检查」：点击对应设备后的「健康检查」按钮，检查结，接口状态、CPU / 内存使用率
5.  查看结果：备份文件自动归档到「backupN1」目录（本地部署直接在项目根目录，Docker 部署可通过容器挂载目录获取），健康检查结果在浏览器页面使用f12,点击控制台就可以看到
#### 方式二：
通过 main.py 统一调度，支持两种模式（backup/检查），两种目标选择（--all/--ip），具体示例如下：
- 模式 1：备份功能
        
        1. 备份所有设备配置：
           python main.py --mode backup --all
        2. 备份指定 IP 的设备（支持多个 IP，空格分隔）：
           python main.py --mode backup --ip 192.168.91.111 192.168.91.112
        备份文件位置：项目根目录的 backupN1 文件夹，文件名格式为 设备IP__配置__年月日-时分秒.txt。
- 模式 2：健康检查功能
  
        1. 检查所有设备健康状态：
           python main.py --mode check --all
        2. 检查指定 IP 的设备健康状态（支持多个 IP，空格分隔）：
           python main.py --mode check --ip 192.168.91.112 192.168.91.113
        检查报告位置：项目根目录的 health_check_report.txt，包含各设备的接口状态、CPU/内存使用率、异常信息。
  
查看帮助文档：
        如需查看命令参数说明，执行：
        python main.py --help

## 五，项目结构

- NetDevOps-Toolbox-V1/ # 项目根目录
  - ├── web/ # Web模块（新增，推荐使用）
  - │   ├── __init__.py
  - │   ├── web_dashboard.py # WEB仪表盘脚本（推荐）
  - │   └── templates/ # Web前端模板目录（存放HTML页面）
  - │       ├── __init__.py
  - │       ├── index.html # Web仪表盘首页/核心操作页面
  - │       └── cloud_demo.html # 云网络概念演示页面（新增）
  - ├── main.py # 统一调度中心（命令行方式，备选）
  - ├── config/ # 配置文件目录（新增）
  - │   ├── devices.yaml # 设备信息配置文件
  - │   ├── nornir_config.yaml # Nornir主配置文件
  - │   └── nornir_inventory.yaml # Nornir框架下的设备清单
  - ├── core/ # 核心功能模块（新增）
  - │   ├── AI/ # AI智能分析模块
  - │   │   └── report_generator.py # 调用AI大模型
  - │   ├── api/ # API模块
  - │   │   └── api_checker.py # 查询云端服务器和设备
  - │   ├── backup/ # 备份功能模块
  - │   │   └── backup_handler.py # 备份功能核心脚本
  - │   ├── cloud/ # 云网络概念模块（新增）
  - │   │   └── concept_simulator.py # 云网络概念模拟器
  - │   ├── health_check/ # 健康检查模块
  - │   │   └── health_checker.py # 健康检查功能核心脚本
  - │   ├── monitoring/ # 系统监控模块
  - │   │   └── monitoring.py # 系统指标收集
  - │   ├── nornir/ # Nornir并发模块
  - │   │   └── nornir_tasks.py # Nornir并发执行任务
  - │   └── __init__.py
  - ├── db/ # 数据库模块（新增）
  - │   ├── __init__.py
  - │   └── database.py # 数据库连接脚本
  - ├── depoly/ # 部署相关（新增）
  - │   ├── Dockerfile
  - │   └── requirements.txt
  - ├── docs/ # 文档目录（新增）
  - │   ├── CHANGELOG.md # 项目演进历史
  - │   └── PROJECT_JOURNEY.md # 王建壮的网络工具箱项目演技和优化的日志
  - ├── reports/ # 报告目录（新增）
  - │   └── __init__.py
  - ├── tests/ # 测试目录（新增）
  - │   ├── __init__.py
  - │   ├── test_device_reader.py # 测试函数脚本
  - │   └── test_integration.py # 测试统一模型整合和测试类型检查脚本
  - ├── utils/ # 工具模块（新增）
  - │   ├── __init__.py
  - │   ├── models.py # 统一数据模型定义
  - │   ├── common.py
  - │   ├── log_setup.py # 创建日志配置模块
  - │   └── retry_decorator.py # 装饰器模块
  - ├── netdevops.db # 数据库（自动生成）
  - ├── backupN1/ # 备份文件归档目录（自动生成）
  - │   ├── 192.168.91.111__配置__20240520-143025.txt
  - │   └── 192.168.91.112__配置__20240520-143030.txt
  - ├── logs/ # 日志文件归档目录（自动生成）
  - │   ├── backup.log
  - │   ├── health_check.log
  - │   └── ...
  - ├── README.md # 项目说明文档（本文件）
  - ├── LICENSE # 开源许可证（MIT）
  └── requirements.txt # 项目依赖


### 致谢

这是我的第一个 NetDevOps 项目，感谢王建壮也就是我自己哈哈，让我逐步掌握 Python 自动化运维在网络领域的应用，脚本可能有点简陋，
以后的王建壮你要改改哈！这才是版本 一 2026.1.1

今天超级开心！让web仪表盘活起来了，中间的原理搞懂后真的好开心 一 2026.1.14

数据库成功建立连接，AI调用成功，Nornir并发执行成功太吊了  —— 2026.1.19



