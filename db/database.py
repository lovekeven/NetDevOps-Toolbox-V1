from datetime import datetime
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
from utils.log_setup import setup_logger
import sqlite3
import logging
import json

# 导入时间datetime模块，使记录可以按天数查询
from datetime import timedelta

DB_PATH = os.path.join(ROOT_DIR, "netdevops.db")
logger = setup_logger("database.py", "database.log")


class DatabaseManager:
    def __init__(self, db_path=None):
        self.path = db_path if db_path else DB_PATH
        self.conn = None
        self.connect()
        self.create_tables()
        logger.debug(f"数据库初始化成功（成功建立连接，插入表格），路径：{self.path}")

    def connect(self):
        try:
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            logger.debug("成功建立数据库连接！")
        except sqlite3.Error as e:
            error_msg = str(e)
            logger.error(f"数据库连接出现错误 {error_msg[:100]}")
            raise

    def create_tables(self):
        sql_commands = [
            # 设备信息表
            """
            CREATE TABLE IF NOT EXISTS devices ( 
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
                hostname TEXT UNIQUE NOT NULL,      
                ip_address TEXT NOT NULL,           
                device_type TEXT,                   
                vendor TEXT,                        
                model TEXT,                         
                status TEXT DEFAULT 'unknown',      
                last_seen TIMESTAMP,                
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            # 备份记录表
            """
            CREATE TABLE IF NOT EXISTS backup_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT NOT NULL,             -- 设备主机名
                backup_path TEXT NOT NULL,          -- 备份文件路径
                backup_size INTEGER,                -- 文件大小（字节）
                status TEXT NOT NULL,               -- 状态: success/failed
                error_message TEXT,                 -- 错误信息（如果失败）
                start_time TIMESTAMP NOT NULL,      -- 开始时间
                end_time TIMESTAMP,                 -- 结束时间
                duration REAL,                      -- 耗时（秒）
                checksum TEXT,                      -- 文件校验和（可选）
                FOREIGN KEY (hostname) REFERENCES devices (hostname)
            );
            """,
            # 健康检查记录表
            """
            CREATE TABLE IF NOT EXISTS health_check_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,  -- 数据库自增主键，唯一标识每条记录
            -- 1:1对应base_result基础字段
            host TEXT NOT NULL,                    -- 设备IP，对应base_result["host"]
            device_name TEXT NOT NULL,             -- 设备名，对应base_result["device_name"]
            version TEXT DEFAULT '未知',            -- 设备版本，对应base_result["version"]
            check_time TEXT NOT NULL,              -- 检查时间，对应base_result["check_time"]（用你统一的字符串格式）
            status TEXT DEFAULT 'unknown',         -- 健康状态，对应base_result["status"]（healthy/degraded/failed）
            check_status TEXT DEFAULT '成功',      -- 检查执行状态，对应base_result["check_status"]（成功/失败）
            -- 1:1对应base_result端口/性能字段
            up_interface INTEGER DEFAULT 0,        -- UP端口数，对应base_result["up_interface"]（数字类型，适配计数）
            down_interface INTEGER DEFAULT 0,      -- DOWN端口数，对应base_result["down_interface"]（数字类型）
            total_interface INTEGER DEFAULT 0,     -- 总端口数，对应base_result["total_interface"]（数字类型）
            CPU_usage TEXT DEFAULT 'N/A',          -- CPU使用率，对应base_result["CPU_usage"]（文本，兼容N/A/%值）
            memory_usage TEXT DEFAULT 'N/A',       -- 内存使用率，对应base_result["memory_usage"]（文本）
            -- 1:1对应base_result错误/问题/可达性字段（2个数据库适配调整）
            error_message TEXT DEFAULT '',         -- 错误信息，对应base_result["error_message"]
            device_health_issues TEXT DEFAULT '',  -- 健康问题列表（适配：列表转分号分隔字符串，如"端口down;CPU过高"）
            reachable TEXT DEFAULT '可达'          -- 设备可达性（适配：布尔转文本，可达/不可达，对应base_result["reachable"]）
            );
            """,
            # 新增：系统指标表
            """
            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,               -- 时间戳（ISO格式字符串）
                cpu_percent REAL NOT NULL,             -- CPU使用率
                memory_percent REAL NOT NULL,          -- 内存使用率
                memory_used_gb REAL NOT NULL,          -- 已用内存(GB)
                memory_total_gb REAL NOT NULL,         -- 总内存(GB)
                disk_percent REAL NOT NULL,            -- 磁盘使用率
                disk_used_gb REAL NOT NULL,            -- 已用磁盘(GB)
                disk_total_gb REAL NOT NULL,           -- 总磁盘(GB)
                network_bytes_sent INTEGER NOT NULL,   -- 发送字节数
                network_bytes_recv INTEGER NOT NULL,   -- 接收字节数
                network_packets_sent INTEGER NOT NULL, -- 发送数据包数
                network_packets_recv INTEGER NOT NULL  -- 接收数据包数
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS physical_device_cards (
                device_id TEXT PRIMARY KEY,  -- 主键：设备名SW1/SW2（和你PhysicalDevice的device_id一致）
                name TEXT NOT NULL,          -- 设备名
                ip_address TEXT NOT NULL,    -- 设备IP（从YAML的hostname来）
                vendor TEXT DEFAULT '未知厂商', -- 厂商（HCLCloud/华为）
                check_status TEXT DEFAULT '未知', -- 检查状态：未知/成功/失败
                up_interfaces TEXT DEFAULT '未知', -- 启用接口数
                down_interface TEXT DEFAULT '未知', -- 禁用接口数（保留你原有笔误dowan_interface，避免报错）
                total_interfaces TEXT DEFAULT '未知', -- 总接口数
                cpu_usage TEXT DEFAULT 'N/A', -- CPU使用率
                memory_usage TEXT DEFAULT 'N/A', -- 内存使用率
                reachable TEXT DEFAULT '未检测', -- 是否可达：未检测/True/False
                version TEXT DEFAULT '未知', -- 设备版本
                status TEXT DEFAULT 'unknown', -- 健康状态：unknown/healthy/degraded/failed（父类NetworkResource的status）
                last_check_time TEXT DEFAULT '未检查', -- 最后检查时间
                create_time TEXT NOT NULL     -- 档案卡创建时间
            );
            """,
            # 新增：配置版本管理表（中优先级 #6）
            """
            CREATE TABLE IF NOT EXISTS config_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT NOT NULL,             -- 设备主机名
                config_content TEXT NOT NULL,       -- 配置内容
                config_hash TEXT NOT NULL,          -- 配置哈希值（用于快速对比）
                version_number INTEGER NOT NULL,    -- 版本号
                backup_path TEXT,                   -- 备份文件路径
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT DEFAULT 'system',   -- 创建者（system/user）
                comment TEXT,                       -- 版本备注
                FOREIGN KEY (hostname) REFERENCES devices (hostname)
            );
            """,
            # 新增：配置合规检查规则表
            """
            CREATE TABLE IF NOT EXISTS compliance_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name TEXT NOT NULL,            -- 规则名称
                rule_type TEXT NOT NULL,            -- 规则类型（password/encryption/aaa/snmp等）
                pattern TEXT NOT NULL,              -- 匹配模式（正则表达式）
                expected_value TEXT,                -- 期望值
                severity TEXT DEFAULT 'warning',    -- 严重程度（critical/warning/info）
                description TEXT,                   -- 规则描述
                enabled INTEGER DEFAULT 1,          -- 是否启用
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            # 新增：合规检查结果表
            """
            CREATE TABLE IF NOT EXISTS compliance_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT NOT NULL,             -- 设备主机名
                rule_id INTEGER NOT NULL,           -- 规则ID
                rule_name TEXT NOT NULL,            -- 规则名称
                passed INTEGER NOT NULL,            -- 是否通过（0/1）
                found_value TEXT,                   -- 发现的值
                check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (hostname) REFERENCES devices (hostname),
                FOREIGN KEY (rule_id) REFERENCES compliance_rules (id)
            );
            """,
            # ============================================================
            # 网络拓扑可视化相关表（一期新增）
            # ============================================================
            # 拓扑节点表：存储发现的网络设备
            """
            CREATE TABLE IF NOT EXISTS topology_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT UNIQUE NOT NULL,       -- 节点唯一标识（IP或设备名）
                name TEXT NOT NULL,                 -- 设备名称
                ip_address TEXT,                    -- IP 地址
                device_type TEXT DEFAULT 'switch',  -- 设备类型：router/switch/firewall/pc/ap
                vendor TEXT,                        -- 厂商：huawei/h3c/cisco
                model TEXT,                         -- 型号
                status TEXT DEFAULT 'online',       -- 状态：online/offline/unknown
                layer TEXT DEFAULT 'access',        -- 网络层级：core/aggregation/access
                sys_descr TEXT,                     -- 系统描述（SNMP sysDescr）
                sys_name TEXT,                      -- 系统名称（SNMP sysName）
                x REAL DEFAULT 0,                   -- 前端 X 坐标（用于保存布局）
                y REAL DEFAULT 0,                   -- 前端 Y 坐标
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            # 拓扑链路表：存储设备间的连接关系
            """
            CREATE TABLE IF NOT EXISTS topology_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_node TEXT NOT NULL,          -- 源节点 ID
                target_node TEXT NOT NULL,          -- 目标节点 ID
                source_port TEXT,                   -- 源端口名
                target_port TEXT,                   -- 目标端口名
                bandwidth TEXT,                     -- 带宽
                status TEXT DEFAULT 'up',           -- 链路状态：up/down
                link_type TEXT DEFAULT 'ethernet',  -- 链路类型：ethernet/fiber/wireless
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_node, target_node, source_port, target_port)
            );
            """,
            # 拓扑快照表：保存历史拓扑用于对比
            """
            CREATE TABLE IF NOT EXISTS topology_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_name TEXT,                 -- 快照名称
                nodes_data TEXT NOT NULL,           -- 节点数据（JSON）
                links_data TEXT NOT NULL,           -- 链路数据（JSON）
                device_count INTEGER DEFAULT 0,     -- 设备数量
                link_count INTEGER DEFAULT 0,       -- 链路数量
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT DEFAULT 'system'
            );
            """,
        ]
        cursor = self.conn.cursor()
        try:
            for command in sql_commands:
                cursor.execute(command)
            self.conn.commit()
            logger.debug("向数据库插入表格成功！")
        except sqlite3.Error as e:
            error_msg = str(e)
            logger.error(f"插入表格失败 {error_msg[:100]}")
            self.conn.rollback()
            raise

    # 向系统指示表中填入数据
    def log_system_metrics(self, metrics_dict):
        try:
            columns = ",".join(
                metrics_dict.keys()
            )  # join 函数的核心要求是，传入一个可迭代对象，且里面的元素必须是字符串
            placeholders = ",".join(["?"] * len(metrics_dict.keys()))
            sql = f"""
            INSERT INTO system_metrics ({columns}) 
            VALUES ({placeholders})
            """
            values = list(metrics_dict.values())
            cursor = self.conn.cursor()
            cursor.execute(sql, values)
            self.conn.commit()
            logger.info("系统指标成功插入数据库！")
        except sqlite3.Error as e:
            error_msg = str(e)
            logger.error(f"向表格写入数据失败 {error_msg[:100]}")
            self.conn.rollback()
            raise

    # 向备份记录表格中填入数据
    def log_backup(
        self, hostname, backup_path, status="success", error_message=None, start_time=None, end_time=None, backup_size=0
    ):
        sql = """
        INSERT INTO backup_records 
        (hostname, backup_path, backup_size, status, error_message, start_time, end_time, duration)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        if start_time is None:
            start_time = datetime.now()
        if end_time is None and status == "success":
            end_time = datetime.now()
        duration = None
        if start_time and end_time:
            duration = (end_time - start_time).total_seconds()
        params = (hostname, backup_path, backup_size, status, error_message, start_time, end_time, duration)
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            self.conn.commit()
            record_id = cursor.lastrowid
            logger.info(f"备份记录已存入数据库，记录ID: {record_id}, 设备: {hostname}, 状态: {status}")
        except sqlite3.Error as e:
            error_msg = str(e)
            logger.error(f"向表格写入数据失败 {error_msg[:100]}")
            self.conn.rollback()
            raise

    # 从数据库拿备份历史信息
    def get_recent_backups(self, hostname=None, limit=None, days=None):
        sql = """
        SELECT * FROM backup_records 
        WHERE 1=1
        """
        params = []
        if hostname:
            sql += " AND hostname = ?"
            params.append(hostname)
        if days and days > 0:
            start_time = datetime.now() - timedelta(days=days)
            sql += " AND start_time >= ?"
            params.append(start_time.isoformat())
        sql += " ORDER BY start_time DESC"
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            results = cursor.fetchall()
            records = [dict(record) for record in results]
            for record in records:
                for key in ["start_time", "end_time"]:
                    if record[key] and isinstance(record[key], datetime):
                        record[key] = record[key].isoformat()
                        # .isoformat() 是时间对象的专属方法,转换成字符串
            logger.debug(f"成功查询到{len(records)}条备份记录")
            return records
        except sqlite3.Error as e:
            logger.error(f"查询备份记录失败: {e}")
            raise

    # 向健康检查表格填入数据
    def log_check_device(self, adapted_result):
        sql = """
        INSERT INTO health_check_records 
        (host, device_name, version, check_time, status, check_status,
        up_interface, down_interface, total_interface, CPU_usage, memory_usage,
        error_message, device_health_issues, reachable)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # 对应SQL的字段值（顺序和SQL里的字段完全一致！）
        values = (
            adapted_result["host"],
            adapted_result["device_name"],
            adapted_result["version"],
            adapted_result["check_time"],
            adapted_result["status"],
            adapted_result["check_status"],
            adapted_result["up_interface"],
            adapted_result["down_interface"],
            adapted_result["total_interface"],
            adapted_result["CPU_usage"],
            adapted_result["memory_usage"],
            adapted_result["error_message"],
            adapted_result["device_health_issues"],
            adapted_result["reachable"],
        )
        cursor = self.conn.cursor()
        try:
            # 连接数据库（SQLite自动创建连接，增删改查后必须提交+关闭）

            cursor.execute(sql, values)
            self.conn.commit()  # 提交事务（关键！不提交数据不会真正写入）
            logger.info(f"设备[{adapted_result['device_name']}]健康检查历史数据入库成功！")
            return True
        except Exception as e:
            logger.error(f"设备[{adapted_result['device_name']}]历史数据入库失败：{str(e)}")
            self.conn.rollback()
            return False

    # 从数据库拿历史健康检查状态信息
    def get_health_check_history(self, device_name=None, limit=None, days=None):
        """
        查询健康检查历史记录，适配健康检查历史表health_check_records
        :param device_name: 设备名（可选，不传查所有设备，传则精准查单设备）
        :param limit: 返回最新的N条记录，默认10条
        :return: 健康检查历史记录列表（字典格式）
        """
        # 基础SQL，WHERE 1=1方便拼接条件
        sql = """
        SELECT * FROM health_check_records 
        WHERE 1=1
        """
        params = []
        # 拼接设备名条件（精准查单设备，适配档案卡单独的历史按钮）
        if device_name:
            sql += " AND device_name = ?"
            params.append(device_name)
        if days and days > 0:
            start_time = datetime.now() - timedelta(days=days)
            sql += " AND check_time >= ?"
            params.append(start_time.isoformat())
        # 按检查时间倒序，限制返回条数（最新的在最前面）
        sql += " ORDER BY check_time DESC"
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = self.conn.cursor()
        try:
            # 执行查询，参数化防SQL注入
            cursor.execute(sql, params)
            results = cursor.fetchall()
            # 把查询结果转成字典（和备份历史一致的格式）
            records = [dict(record) for record in results]
            # 日志打印查询结果数
            logger.debug(f"成功查询到{len(records)}条健康检查历史记录")
            return records
        except sqlite3.Error as e:
            # 异常日志+抛错，和备份历史的异常处理一致
            logger.error(f"查询健康检查历史记录失败: {e}")
            raise

    # 往空白表里填单条档案卡数据
    def add_physical_card(self, card_dict):
        """
        单张物理设备档案卡写入数据库
        :param card_dict: PhysicalDevice对象转的字典（含所有字段）
        """
        sql = """
        INSERT OR REPLACE INTO physical_device_cards 
        (device_id, name, ip_address, vendor, check_status, up_interfaces, down_interface, 
         total_interfaces, cpu_usage, memory_usage, reachable, version, status, 
         last_check_time, create_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # 按表字段顺序取值，和PhysicalDevice属性严格对齐
        params = (
            card_dict["id"],
            card_dict["name"],
            card_dict["ip_address"],
            card_dict.get("vendor", "未知厂商"),
            card_dict.get("check_status", "未知"),
            card_dict.get("up_interfaces", "未知"),
            card_dict.get("down_interface", "未知"),
            card_dict.get("total_interfaces", "未知"),
            card_dict.get("cpu_usage", "N/A"),
            card_dict.get("memory_usage", "N/A"),
            card_dict.get("reachable", "未检测"),
            card_dict.get("version", "未知"),
            card_dict.get("status", "unknown"),
            card_dict.get("last_check", "未检查"),
            card_dict["create_time"],
        )
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            self.conn.commit()
            logger.info(f"档案卡写入数据库成功：设备[{card_dict['name']}]")
        except sqlite3.Error as e:
            error_msg = str(e)
            logger.error(f"档案卡写入数据库失败 {card_dict['name']}：{error_msg[:100]}")
            self.conn.rollback()
            raise

    def batch_add_physical_cards(self, card_list):
        """
        批量写入物理设备档案卡（适配你从YAML加载的档案卡列表）
        :param card_list: PhysicalDevice对象转的字典列表
        """
        if not card_list:
            logger.warning("无档案卡可批量写入数据库")
            return
        for card in card_list:  # card是字典，card_list是列表元素是字典,原来的档案卡列表元素是对象
            self.add_physical_card(card)
        logger.info(f"批量写入数据库完成！共{len(card_list)}张物理设备档案卡存入数据库")

    def get_all_physical_cards(self):
        """
        从数据库读取所有物理设备档案卡
        :return: 字典列表（后续可直接转PhysicalDevice对象）
        """
        sql = "SELECT * FROM physical_device_cards ORDER BY device_id"
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql)
            results = cursor.fetchall()
            # 转成字典列表，方便后续实例化PhysicalDevice
            card_list = [dict(card) for card in results]
            logger.info(f"从数据库读取{len(card_list)}张物理设备档案卡")
            return card_list
        except sqlite3.Error as e:
            logger.error(f"读取档案卡失败：{str(e)[:100]}")
            # 原代码：self.conn.rollback()  # 问题：SELECT 查询不需要 rollback，只有 INSERT/UPDATE/DELETE 才需要
            # 修复：移除 rollback，SELECT 失败不影响数据一致性
            raise

    def update_physical_card(self, card_dict):
        """
        更新数据库中的物理设备档案卡（健康检查后调用，实现持久化）
        :param card_dict: 更新后的PhysicalDevice对象转的字典
        """
        sql = """
        UPDATE physical_device_cards 
        SET check_status=?, up_interfaces=?, down_interface=?, total_interfaces=?, 
            cpu_usage=?, memory_usage=?, reachable=?, version=?, status=?, last_check_time=?
        WHERE device_id = ?
        """
        params = (
            card_dict.get("check_status", "未知"),
            card_dict.get("up_interfaces", "未知"),
            card_dict.get("down_interface", "未知"),
            card_dict.get("total_interfaces", "未知"),
            card_dict.get("cpu_usage", "N/A"),
            card_dict.get("memory_usage", "N/A"),
            card_dict.get("reachable", "未检测"),
            card_dict.get("version", "未知"),
            card_dict.get("status", "unknown"),
            card_dict.get("last_check_time", "未检查"),  # 修正：使用正确的字段名
            card_dict["id"],  # 更新条件：主键device_id（SW1/SW2）
        )
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            self.conn.commit()
            logger.info(f"档案卡更新成功：设备[{card_dict['name']}]")
        except sqlite3.Error as e:
            error_msg = str(e)
            logger.error(f"档案卡更新失败 {card_dict['name']}：{error_msg[:100]}")
            self.conn.rollback()
            raise

    def close(self):
        if self.conn:
            self.conn.close()
            logger.debug("数据库已经关闭连接")

    def __del__(self):
        self.close()

    # ============================================================
    # 配置版本管理功能（中优先级 #6）
    # ============================================================

    def save_config_version(self, hostname, config_content, backup_path=None, created_by='system', comment=None):
        """
        保存配置版本
        :param hostname: 设备主机名
        :param config_content: 配置内容
        :param backup_path: 备份文件路径
        :param created_by: 创建者（system/user）
        :param comment: 版本备注
        :return: 版本ID
        """
        import hashlib
        config_hash = hashlib.md5(config_content.encode('utf-8')).hexdigest()

        # 获取当前最大版本号
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(version_number) FROM config_versions WHERE hostname = ?", (hostname,))
        result = cursor.fetchone()
        max_version = result[0] if result[0] else 0
        new_version = max_version + 1

        sql = """
        INSERT INTO config_versions (hostname, config_content, config_hash, version_number, backup_path, created_by, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (hostname, config_content, config_hash, new_version, backup_path, created_by, comment)

        try:
            cursor.execute(sql, params)
            self.conn.commit()
            version_id = cursor.lastrowid
            logger.info(f"配置版本保存成功：设备={hostname}，版本={new_version}，ID={version_id}")
            return version_id
        except sqlite3.Error as e:
            logger.error(f"保存配置版本失败：{e}")
            self.conn.rollback()
            raise

    def get_config_versions(self, hostname, limit=10):
        """
        获取设备的配置版本列表
        :param hostname: 设备主机名
        :param limit: 返回记录数
        :return: 版本列表
        """
        sql = """
        SELECT id, hostname, config_hash, version_number, backup_path, created_at, created_by, comment
        FROM config_versions
        WHERE hostname = ?
        ORDER BY version_number DESC
        LIMIT ?
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, (hostname, limit))
            results = cursor.fetchall()
            versions = [dict(record) for record in results]
            logger.info(f"查询到 {len(versions)} 个配置版本：设备={hostname}")
            return versions
        except sqlite3.Error as e:
            logger.error(f"查询配置版本失败：{e}")
            raise

    def get_config_content(self, version_id):
        """
        获取指定版本的配置内容
        :param version_id: 版本ID
        :return: 配置内容
        """
        sql = "SELECT config_content FROM config_versions WHERE id = ?"
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, (version_id,))
            result = cursor.fetchone()
            if result:
                return result[0]
            return None
        except sqlite3.Error as e:
            logger.error(f"获取配置内容失败：{e}")
            raise

    def compare_configs(self, version_id1, version_id2):
        """
        对比两个配置版本
        :param version_id1: 版本ID1
        :param version_id2: 版本ID2
        :return: 对比结果
        """
        config1 = self.get_config_content(version_id1)
        config2 = self.get_config_content(version_id2)

        if config1 is None or config2 is None:
            return None

        # 简单的diff对比
        lines1 = config1.splitlines()
        lines2 = config2.splitlines()

        added = []
        removed = []
        unchanged = []

        # 使用difflib进行对比
        import difflib
        diff = list(difflib.unified_diff(lines1, lines2, lineterm=''))

        for line in diff:
            if line.startswith('+') and not line.startswith('+++'):
                added.append(line[1:])
            elif line.startswith('-') and not line.startswith('---'):
                removed.append(line[1:])

        return {
            'version_id1': version_id1,
            'version_id2': version_id2,
            'added': added,
            'removed': removed,
            'total_added': len(added),
            'total_removed': len(removed),
            'is_identical': len(added) == 0 and len(removed) == 0
        }

    # ============================================================
    # 合规检查功能（中优先级 #6）
    # ============================================================

    def add_compliance_rule(self, rule_name, rule_type, pattern, expected_value=None, severity='warning', description=None):
        """
        添加合规检查规则
        :param rule_name: 规则名称
        :param rule_type: 规则类型
        :param pattern: 匹配模式（正则表达式）
        :param expected_value: 期望值
        :param severity: 严重程度
        :param description: 规则描述
        :return: 规则ID
        """
        sql = """
        INSERT INTO compliance_rules (rule_name, rule_type, pattern, expected_value, severity, description)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (rule_name, rule_type, pattern, expected_value, severity, description)
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            self.conn.commit()
            rule_id = cursor.lastrowid
            logger.info(f"合规规则添加成功：{rule_name}，ID={rule_id}")
            return rule_id
        except sqlite3.Error as e:
            logger.error(f"添加合规规则失败：{e}")
            self.conn.rollback()
            raise

    def get_compliance_rules(self, rule_type=None, enabled_only=True):
        """
        获取合规检查规则
        :param rule_type: 规则类型（可选）
        :param enabled_only: 是否只返回启用的规则
        :return: 规则列表
        """
        sql = "SELECT * FROM compliance_rules WHERE 1=1"
        params = []

        if rule_type:
            sql += " AND rule_type = ?"
            params.append(rule_type)

        if enabled_only:
            sql += " AND enabled = 1"

        sql += " ORDER BY id"

        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            results = cursor.fetchall()
            rules = [dict(record) for record in results]
            logger.info(f"查询到 {len(rules)} 条合规规则")
            return rules
        except sqlite3.Error as e:
            logger.error(f"查询合规规则失败：{e}")
            raise

    def save_compliance_result(self, hostname, rule_id, rule_name, passed, found_value=None):
        """
        保存合规检查结果
        :param hostname: 设备主机名
        :param rule_id: 规则ID
        :param rule_name: 规则名称
        :param passed: 是否通过
        :param found_value: 发现的值
        """
        sql = """
        INSERT INTO compliance_results (hostname, rule_id, rule_name, passed, found_value)
        VALUES (?, ?, ?, ?, ?)
        """
        params = (hostname, rule_id, rule_name, 1 if passed else 0, found_value)
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            self.conn.commit()
            logger.info(f"合规检查结果保存成功：设备={hostname}，规则={rule_name}，通过={passed}")
        except sqlite3.Error as e:
            logger.error(f"保存合规检查结果失败：{e}")
            self.conn.rollback()
            raise

    def get_compliance_results(self, hostname=None, limit=100):
        """
        获取合规检查结果
        :param hostname: 设备主机名（可选）
        :param limit: 返回记录数
        :return: 结果列表
        """
        sql = "SELECT * FROM compliance_results WHERE 1=1"
        params = []

        if hostname:
            sql += " AND hostname = ?"
            params.append(hostname)

        sql += " ORDER BY check_time DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            results = cursor.fetchall()
            records = [dict(record) for record in results]
            logger.info(f"查询到 {len(records)} 条合规检查结果")
            return records
        except sqlite3.Error as e:
            logger.error(f"查询合规检查结果失败：{e}")
            raise

    # ============================================================
    # 拓扑相关方法（一期新增）
    # ============================================================

    # 保存单个拓扑节点，存在就更新
    def save_topology_node(self, node_dict):
        sql = """
        INSERT OR REPLACE INTO topology_nodes
        (node_id, name, ip_address, device_type, vendor, model, status, layer, sys_descr, sys_name, x, y, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """
        params = (
            node_dict.get("node_id"),
            node_dict.get("name", "未知设备"),
            node_dict.get("ip_address"),
            node_dict.get("device_type", "switch"),
            node_dict.get("vendor"),
            node_dict.get("model"),
            node_dict.get("status", "online"),
            node_dict.get("layer", "access"),
            node_dict.get("sys_descr"),
            node_dict.get("sys_name"),
            node_dict.get("x", 0),
            node_dict.get("y", 0),
        )
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            self.conn.commit()
            logger.info(f"拓扑节点保存成功：{node_dict.get('name')}")
        except sqlite3.Error as e:
            logger.error(f"拓扑节点保存失败：{e}")
            self.conn.rollback()
            raise

    # 批量保存拓扑节点（用单个事务，比逐条 commit 快很多）
    def batch_save_topology_nodes(self, node_list):
        if not node_list:
            return
        sql = """
        INSERT OR REPLACE INTO topology_nodes
        (node_id, name, ip_address, device_type, vendor, model, status, layer, sys_descr, sys_name, x, y, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """
        cursor = self.conn.cursor()
        try:
            for node in node_list:
                params = (
                    node.get("node_id"),
                    node.get("name", "未知设备"),
                    node.get("ip_address"),
                    node.get("device_type", "switch"),
                    node.get("vendor"),
                    node.get("model"),
                    node.get("status", "online"),
                    node.get("layer", "access"),
                    node.get("sys_descr"),
                    node.get("sys_name"),
                    node.get("x", 0),
                    node.get("y", 0),
                )
                cursor.execute(sql, params)
            self.conn.commit()
            logger.info(f"批量保存拓扑节点完成，共{len(node_list)}个")
        except sqlite3.Error as e:
            logger.error(f"批量保存拓扑节点失败：{e}")
            self.conn.rollback()
            raise

    # 获取所有拓扑节点
    def get_all_topology_nodes(self):
        sql = "SELECT * FROM topology_nodes ORDER BY layer, name"
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql)
            results = cursor.fetchall()
            nodes = [dict(r) for r in results]
            logger.info(f"读取到{len(nodes)}个拓扑节点")
            return nodes
        except sqlite3.Error as e:
            logger.error(f"读取拓扑节点失败：{e}")
            raise

    # 清空拓扑节点（重新扫描前用）
    def clear_topology_nodes(self):
        cursor = self.conn.cursor()
        try:
            cursor.execute("DELETE FROM topology_nodes")
            self.conn.commit()
            logger.info("拓扑节点表已清空")
        except sqlite3.Error as e:
            logger.error(f"清空拓扑节点失败：{e}")
            self.conn.rollback()
            raise

    # 保存链路，存在就跳过
    def save_topology_link(self, link_dict):
        sql = """
        INSERT OR IGNORE INTO topology_links
        (source_node, target_node, source_port, target_port, bandwidth, status, link_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            link_dict.get("source_node"),
            link_dict.get("target_node"),
            link_dict.get("source_port"),
            link_dict.get("target_port"),
            link_dict.get("bandwidth"),
            link_dict.get("status", "up"),
            link_dict.get("link_type", "ethernet"),
        )
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"拓扑链路保存失败：{e}")
            self.conn.rollback()
            raise

    # 批量保存链路（用单个事务）
    def batch_save_topology_links(self, link_list):
        if not link_list:
            return
        sql = """
        INSERT OR IGNORE INTO topology_links
        (source_node, target_node, source_port, target_port, bandwidth, status, link_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        cursor = self.conn.cursor()
        try:
            for link in link_list:
                params = (
                    link.get("source_node"),
                    link.get("target_node"),
                    link.get("source_port"),
                    link.get("target_port"),
                    link.get("bandwidth"),
                    link.get("status", "up"),
                    link.get("link_type", "ethernet"),
                )
                cursor.execute(sql, params)
            self.conn.commit()
            logger.info(f"批量保存拓扑链路完成，共{len(link_list)}条")
        except sqlite3.Error as e:
            logger.error(f"批量保存拓扑链路失败：{e}")
            self.conn.rollback()
            raise

    # 获取所有拓扑链路
    def get_all_topology_links(self):
        sql = "SELECT * FROM topology_links"
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql)
            results = cursor.fetchall()
            links = [dict(r) for r in results]
            logger.info(f"读取到{len(links)}条拓扑链路")
            return links
        except sqlite3.Error as e:
            logger.error(f"读取拓扑链路失败：{e}")
            raise

    # 清空拓扑链路
    def clear_topology_links(self):
        cursor = self.conn.cursor()
        try:
            cursor.execute("DELETE FROM topology_links")
            self.conn.commit()
            logger.info("拓扑链路表已清空")
        except sqlite3.Error as e:
            logger.error(f"清空拓扑链路失败：{e}")
            self.conn.rollback()
            raise

    # 保存拓扑快照
    def save_topology_snapshot(self, snapshot_name, nodes_data, links_data):
        import json
        sql = """
        INSERT INTO topology_snapshots
        (snapshot_name, nodes_data, links_data, device_count, link_count)
        VALUES (?, ?, ?, ?, ?)
        """
        nodes_json = json.dumps(nodes_data, ensure_ascii=False)
        links_json = json.dumps(links_data, ensure_ascii=False)
        params = (snapshot_name, nodes_json, links_json, len(nodes_data), len(links_data))
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, params)
            self.conn.commit()
            snapshot_id = cursor.lastrowid
            logger.info(f"拓扑快照保存成功：{snapshot_name}，ID={snapshot_id}")
            return snapshot_id
        except sqlite3.Error as e:
            logger.error(f"保存拓扑快照失败：{e}")
            self.conn.rollback()
            raise

    # 获取拓扑快照列表
    def get_topology_snapshots(self, limit=20):
        sql = "SELECT id, snapshot_name, device_count, link_count, created_at FROM topology_snapshots ORDER BY created_at DESC LIMIT ?"
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, (limit,))
            results = cursor.fetchall()
            snapshots = [dict(r) for r in results]
            return snapshots
        except sqlite3.Error as e:
            logger.error(f"查询拓扑快照失败：{e}")
            raise

    # 获取某个快照的完整数据
    def get_topology_snapshot_detail(self, snapshot_id):
        import json
        sql = "SELECT * FROM topology_snapshots WHERE id = ?"
        cursor = self.conn.cursor()
        try:
            cursor.execute(sql, (snapshot_id,))
            result = cursor.fetchone()
            if result:
                snapshot = dict(result)
                snapshot["nodes_data"] = json.loads(snapshot["nodes_data"])
                snapshot["links_data"] = json.loads(snapshot["links_data"])
                return snapshot
            return None
        except sqlite3.Error as e:
            logger.error(f"获取拓扑快照详情失败：{e}")
            raise


db_manager = DatabaseManager()
