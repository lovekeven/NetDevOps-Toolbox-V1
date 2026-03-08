# NetDevOps-Toolbox-V1
## ✨ 最新进展：项目已升级为智能数据化系统（V7.2）！
- **日期**：2026年3月8日
- **里程碑**：新增Docker容器化部署，GitHub Actions自动化CI/CD，支持阿里云镜像仓库一键拉取
- **核心功能**：
    - 🗃️ **数据持久化**：集成SQLite数据库，扩展设备检查健康状态，物理设备档案卡数据表，实现设备/系统/服务数据全量存储与追溯。
    - 🤖 **AI智能分析**：接入大模型API，可根据自动生成智能运维报告，并且一键发送到邮箱。
    - ⚡ **专业并发框架**：优化Nornir框架逻辑，根据实际情况判断设备是否健康。
    - 📈 **系统可观测性**：完成全维度监控体系建设（系统级指标/API服务/Nornir框架/Web仪表盘），支持实时状态查询与阈值告警。
    - 🌐 **API能力扩展**：主要新增添加设备，和删除设备以及发送邮件的API接口。
    - 🐳 **容器化部署**：支持Docker一键部署，无需克隆项目，直接拉取镜像即可运行。
    - 🔄 **自动化CI/CD**：GitHub Actions自动构建并推送镜像到阿里云容器镜像服务。
- **技术栈**：Python, Flask, SQLite, Nornir, Netmiko, AI API, RESTful API, psutil（系统监控）
- **体验地址**：Docker 一键部署 `docker pull registry.cn-hangzhou.aliyuncs.com/nick1522928711/wangjianzhuangdedocker:latest`，即可在浏览器访问 `http://localhost:8080`（点击「检查系统服务状态」体验监控功能）
## 一，项目描述
这是一款基于 Python 开发的网络设备自动化运维工具，能批量完成网络设备的配置备份和健康状态检查（接口、CPU、内存），通过Web仪表盘统一操作，解决传统手动运维效率低、易出错的问题。同时在前端增加云网络，和混合云平台
## 二，功能特性
- 自动化备份：支持批量备份指定/所有设备的接口配置，文件按IP+时间戳归档，支持在前端页面下载备份结果，并且可以按天数，记录数查询备份历史
- 健康检查：自动统计设备接口UP/DOWN数量、CPU使用率、内存使用率，同样也支持按天数，记录数查询备份历史
- 异常提示：连接失败时精准提示原因（认证失败、超时、IP不可达等），并且在后端改为多线程处理，加载页面慢的原因，后端在判断设备是否连接成功
- 配置灵活：设备信息通过前端“添加设备按钮”，直接添加用户所需设备，并且支持删除设备
- AI分析：升级AI分析报告，可以分别对备份历史，和健康历史进行AI分析。对设备健康历史分析时，增加对单个设备那些天数的历史分析，和对所有设备的历史分析，增加灵活性
- 邮件发送：AI分析完毕后，支持一键发送到邮箱（指定邮箱发送可视化还在开发中），和每周自动发送邮箱
- 档案卡查询：档案卡接入数据库，显示最后一次的检查状态，和检查时间。方便用户查询和管理
- 云网络引入：可以切换模拟和真实API模式，对接真实阿里云
- 混合云平台：支持真实物理设备和真实云资源的查看，根据资源ID的查询，并且可以直观看到所关注的资源的健康（后端判断健康同样判断真实数据，具体详情还在开发中），
## 三，技术栈
- 核心语言：Python 3.8+
- 网络设备连接：Netmiko
- 配置文件解析：PyYAML
- 命令行参数：argparse
- 后端服务器搭建：flask
- 发送API请求：requests
## 四，安装与使用

### 1. 环境部署方式（二选一，按需选择）
> 说明：两种部署方式均可实现项目运行，无需同时操作，按需挑选即可。

#### 方式一：Docker 容器化部署（推荐新手 / 快速启动 / 无需克隆项目）
1.  前提准备：本地已安装「Docker Desktop」（Windows/Mac）或「Docker Engine」（Linux），且 Docker 服务已启动；
2.  拉取镜像并运行（一行命令即可）：
    ```bash
    # 拉取镜像
    docker pull registry.cn-hangzhou.aliyuncs.com/nick1522928711/wangjianzhuangdedocker:latest
    
    # 运行容器
    docker run -d -p 8080:8080 --name netdevops-app registry.cn-hangzhou.aliyuncs.com/nick1522928711/wangjianzhuangdedocker:latest
    ```
    > 说明：镜像已通过 GitHub Actions 自动构建并推送到阿里云容器镜像服务，无需克隆项目
3.  打开浏览器访问：http://127.0.0.1:8080

#### 方式二：本地Python环境部署（适合开发者/需修改代码的用户）
1.  克隆项目：
    ```bash
    git clone https://github.com/lovekeven/NetDevOps-Toolbox-V1.git
    cd NetDevOps-Toolbox-V1
    ```
2.  前提准备：已安装Python 3.8+（推荐3.9~3.11版本，兼容性更好）；
3.  安装依赖：
    ```bash
    pip install -r requirements.txt
    ```
4.  启动服务：
    ```bash
    python web/web_dashboard.py
    ```
5.  打开浏览器访问：http://127.0.0.1:8080
### 2. 设备配置文件编写
1.直接在前端页面添加设备处，更新和删除设备

### 3. Web仪表盘操作说明
服务启动后，打开浏览器访问 http://127.0.0.1:8080：
1.  进入页面后，可直观看到所有设备列表；
2.  执行「设备备份」：点击对应设备后的「备份」按钮，等待操作完成（页面会实时显示「备份中→备份成功」反馈）
3.  执行「健康检查」：点击对应设备后的「健康检查」按钮，检查接口状态、CPU / 内存使用率
4.  查看结果：备份文件自动归档到「backupN1」目录，健康检查结果在浏览器页面使用F12点击控制台可以看到

### 4. 命令行方式（可选）
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
  - ├── main.py # 统一调度中心（命令行方式，备选）
  - ├── config/ # 配置文件目录（新增）
  - │   ├── devices.yaml # 设备信息配置文件
  - │   ├── nornir_config.yaml # Nornir主配置文件
  - │   ├── nornir_inventory.yaml # Nornir框架下的设备清单
  - │   ├── cloud_resources.yaml # 云资源配置（新增）
  - │   └── emali_config.py # 邮件配置（新增）
  - ├── core/ # 核心功能模块（新增）
  - │   ├── AI/ # AI智能分析模块
  - │   │   └── report_generator.py # 调用AI大模型
  - │   ├── api/ # API模块
  - │   │   └── api_checker.py # 查询云端服务器和设备
  - │   ├── backup/ # 备份功能模块
  - │   │   └── backup_handler.py # 备份功能核心脚本
  - │   ├── cloud/ # 云网络概念模块（新增）
  - │   │   ├── real_providers/ # 真实云服务提供商（新增）
  - │   │   │   ├── __init__.py
  - │   │   │   └── ali_client.py # 阿里云客户端（新增）
  - │   │   └── concept_simulator.py # 云网络概念模拟器
  - │   ├── Email/ # 邮件发送模块（新增）
  - │   │   └── auto_send_report.py # 自动发送报告（新增）
  - │   ├── health_check/ # 健康检查模块
  - │   │   └── health_checker.py # 健康检查功能核心脚本
  - │   ├── hybrid_manager/ # 混合云管理模块（新增）
  - │   │   └── hybrid_manager.py # 混合云资源管理（新增）
  - │   ├── monitoring/ # 系统监控模块
  - │   │   └── monitoring.py # 系统指标收集
  - │   ├── nornir/ # Nornir并发模块
  - │   │   └── nornir_tasks.py # Nornir并发执行任务
  - │   └── __init__.py
  - ├── db/ # 数据库模块（新增）
  - │   ├── __init__.py
  - │   ├── database.py # 数据库连接脚本
  - ├── depoly/ # 部署相关（新增）
  - │   ├── Dockerfile
  - │   └── requirements.txt
  - ├── docs/ # 文档目录（新增）
  - │   ├── CHANGELOG.md # 项目演进历史
  - │   └── PROJECT_JOURNEY.md # 项目演进和优化日志
  - ├── reports/ # 报告目录（新增）
  - │   └── __init__.py
  - ├── tests/ # 测试目录（新增）
  - │   ├── __init__.py
  - │   ├── test_device_reader.py # 测试函数脚本
  - │   ├── test_hybrid_manager.py # 测试混合云管理器（新增）
  - │   ├── test_integration.py # 测试统一模型整合
  - │   └── test_models.py # 测试数据模型（新增）
  - ├── utils/ # 工具模块（新增）
  - │   ├── __init__.py
  - │   ├── models.py # 统一数据模型定义
  - │   ├── log_setup.py # 创建日志配置模块
  - │   ├── retry_decorator.py # 装饰器模块
  - │   ├── aliyun_time.py # 阿里云时间工具（新增）
  - │   ├── email_sender.py # 邮件发送工具（新增）
  - │   └── valid_ipv4.py # IP地址验证工具（新增）
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

这次优化的很多，隔了这么长时间优化项目，感觉都不是自己做的了，哈哈，太厉害了！ —— 2026.3.7



