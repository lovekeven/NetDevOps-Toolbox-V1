# NetDevOps-Toolbox-V1
## ✨ 最新进展：项目已升级为智能数据化系统（V8.0）！
- **日期**：2026年6月5日
- **里程碑**：新增网络拓扑可视化功能，支持传统网络 SNMP 探测和 SDN 控制器对接
- **核心功能**：
    - 🗺️ **网络拓扑可视化**：支持 SNMP+LLDP 自动发现网络拓扑，可视化展示设备连接关系
    - 🔀 **双模切换**：传统网络探测模式 / SDN 控制器模式（Ryu）一键切换
    - 🛠️ **网络工具箱**：Ping、端口扫描、网段扫描、Traceroute、LLDP 查询
    - 🚨 **故障告警**：设备离线自动弹窗告警，Toast 通知
    - 💾 **批量备份**：一键批量备份所有设备配置
    - ✏️ **拓扑编辑**：支持手动添加/删除设备，自定义拓扑布局
    - 🎨 **专业图标**：10种设备类型 FontAwesome 图标（路由器/交换机/防火墙/PC/服务器等）
    - 🗃️ **数据持久化**：集成SQLite数据库，拓扑快照、设备档案卡、备份记录全量存储
    - 🤖 **AI智能分析**：接入大模型API，自动生成智能运维报告
    - 📈 **系统可观测性**：全维度监控体系建设，支持实时状态查询与阈值告警
    - 🐳 **容器化部署**：支持Docker一键部署
- **技术栈**：Python, Flask, SQLite, Nornir, Netmiko, pysnmp, vis.js, AI API, psutil
- **体验地址**：Docker 一键部署 `docker pull crpi-wxw6k2suvvg9fa0s.cn-hangzhou.personal.cr.aliyuncs.com/zhuangdedocker/wangjianzhuangdedocker:latest`，即可在浏览器访问 `http://localhost:8080`
## 一，项目描述
这是一款基于 Python 开发的网络设备自动化运维工具，能批量完成网络设备的配置备份和健康状态检查（接口、CPU、内存），通过Web仪表盘统一操作，解决传统手动运维效率低、易出错的问题。同时在前端增加云网络，和混合云平台
## 二，功能特性

### 🗺️ 网络拓扑可视化（V8.0 新增）
- **SNMP 拓扑发现**：输入种子设备IP，通过 SNMP+LLDP 自动发现全网设备和链路
- **双模切换**：支持传统网络探测模式和 SDN 控制器模式（Ryu）
- **网络工具箱**：Ping 连通测试、TCP 端口扫描、网段存活扫描、Traceroute 路径追踪、LLDP 邻居查询
- **故障告警**：设备离线自动弹窗告警，Toast 通知提醒
- **拓扑编辑**：支持手动添加/删除设备，拖拽调整布局
- **快照管理**：保存拓扑快照，支持历史对比
- **导出功能**：支持导出 PNG 图片和 JSON 数据
- **设备图标**：10种设备类型专业图标（路由器/交换机/防火墙/PC/服务器/AP/云/打印机/摄像头/电话）

### 🛠️ 基础运维功能
- **自动化备份**：支持批量备份指定/所有设备的配置，文件按IP+时间戳归档
- **健康检查**：自动统计设备接口UP/DOWN数量、CPU使用率、内存使用率
- **异常提示**：连接失败时精准提示原因（认证失败、超时、IP不可达等）
- **配置灵活**：设备信息通过前端添加和删除

### 🤖 智能分析
- **AI分析报告**：接入大模型API，自动生成智能运维报告
- **邮件发送**：支持一键发送报告到邮箱，和每周自动发送

### ☁️ 云网络与混合云
- **云网络引入**：可以切换模拟和真实API模式，对接真实阿里云
- **混合云平台**：支持真实物理设备和真实云资源的统一管理
## 三，技术栈
- **核心语言**：Python 3.8+
- **Web框架**：Flask + Flask-SocketIO
- **数据库**：SQLite
- **网络设备连接**：Netmiko + Nornir
- **SNMP采集**：pysnmp
- **前端可视化**：vis.js（拓扑图）+ ECharts（图表）
- **系统监控**：psutil
- **AI集成**：DeepSeek API
- **云服务**：阿里云 SDK
- **容器化**：Docker + GitHub Actions CI/CD
## 四，安装与使用

### 1. 环境部署方式（二选一，按需选择）
> 说明：两种部署方式均可实现项目运行，无需同时操作，按需挑选即可。

#### 方式一：Docker 容器化部署（推荐新手 / 快速启动 / 无需克隆项目）
1.  前提准备：本地已安装「Docker Desktop」（Windows/Mac）或「Docker Engine」（Linux），且 Docker 服务已启动；
2.  拉取镜像并运行（一行命令即可）：
    ```bash
    # 拉取镜像
    docker pull crpi-wxw6k2suvvg9fa0s.cn-hangzhou.personal.cr.aliyuncs.com/zhuangdedocker/wangjianzhuangdedocker:latest
    
    # 运行容器
    docker run -d -p 8080:8080 --name netdevops-app crpi-wxw6k2suvvg9fa0s.cn-hangzhou.personal.cr.aliyuncs.com/zhuangdedocker/wangjianzhuangdedocker:latest
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

```
NetDevOps-Toolbox-V1/
├── web/                          # Web 模块
│   ├── web_dashboard.py          # Web 仪表盘主程序
│   ├── static/js/
│   │   └── topology.js           # 拓扑可视化模块
│   └── templates/
│       └── index.html            # 前端页面
├── core/                         # 核心功能模块
│   ├── topology/                 # 网络拓扑模块（V8.0 新增）
│   │   ├── snmp_collector.py     # SNMP 采集器
│   │   ├── sdn_collector.py      # SDN 控制器采集器（Ryu）
│   │   ├── topology_builder.py   # 拓扑算法构建器
│   │   └── network_tools.py      # 网络工具集（Ping/端口/Traceroute）
│   ├── AI/                       # AI 智能分析模块
│   ├── backup/                   # 备份功能模块
│   ├── health_check/             # 健康检查模块
│   ├── cloud/                    # 云网络模块
│   ├── monitoring/               # 系统监控模块
│   └── nornir/                   # Nornir 并发模块
├── db/
│   └── database.py               # 数据库管理（SQLite）
├── config/                       # 配置文件目录
├── utils/                        # 工具模块
├── docs/                         # 文档目录
├── main.py                       # 命令行调度中心
├── Dockerfile                    # Docker 部署文件
├── requirements.txt              # 项目依赖
└── README.md                     # 项目说明文档
```

### 数据库表结构
| 表名 | 说明 |
|------|------|
| devices | 设备信息表 |
| backup_records | 备份记录表 |
| health_check_records | 健康检查记录表 |
| physical_device_cards | 物理设备档案卡 |
| topology_nodes | 拓扑节点表 |
| topology_links | 拓扑链路表 |
| topology_snapshots | 拓扑快照表 |
| system_metrics | 系统指标表 |
| config_versions | 配置版本表 |
| compliance_rules | 合规检查规则表 |


### 致谢

这是我的第一个 NetDevOps 项目，感谢王建壮也就是我自己哈哈，让我逐步掌握 Python 自动化运维在网络领域的应用，脚本可能有点简陋，
以后的王建壮你要改改哈！这才是版本 一 2026.1.1

今天超级开心！让web仪表盘活起来了，中间的原理搞懂后真的好开心 一 2026.1.14

数据库成功建立连接，AI调用成功，Nornir并发执行成功太吊了  —— 2026.1.19

这次优化的很多，隔了这么长时间优化项目，感觉都不是自己做的了，哈哈，太厉害了！ —— 2026.3.7

网络拓扑可视化功能完成！支持 SNMP 拓扑发现、SDN 控制器对接、网络工具箱，三期迭代开发，终于搞定了！ —— 2026.6.5

