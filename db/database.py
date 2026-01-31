from datetime import datetime
from optparse import Values
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
from utils.log_setup import setup_logger
import sqlite3
import logging
import json

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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT NOT NULL,
                check_type TEXT NOT NULL,           -- 检查类型: ping/ssh/cpu/memory
                result_json TEXT NOT NULL,          -- 检查结果（JSON格式）
                status TEXT NOT NULL,               -- 状态: passed/failed
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (hostname) REFERENCES devices (hostname)
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
    def get_recent_backups(self, hostname=None, limit=10):
        sql = """
        SELECT * FROM backup_records 
        WHERE 1=1
        """
        params = []
        if hostname:
            sql += " AND hostname = ?"
            params.append(hostname)
        sql += " ORDER BY start_time DESC LIMIT ?"
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
            self.conn.rollback()
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
            card_dict.get("last_check", "未检查"),
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


db_manager = DatabaseManager()
