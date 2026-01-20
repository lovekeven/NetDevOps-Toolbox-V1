from datetime import datetime
from optparse import Values
from log_setup import setup_logger
import sqlite3
import logging
import json

logger = setup_logger("database.py", "database.log")


class DatabaseManager:
    def __init__(self, db_path="netdevops.db"):
        self.path = db_path
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

    def close(self):
        if self.conn:
            self.conn.close()
            logger.debug("数据库已经关闭连接")

    def __del__(self):
        self.close()


db_manager = DatabaseManager()
