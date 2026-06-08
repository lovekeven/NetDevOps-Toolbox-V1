"""
Web 终端模块
实现 SSH 连接和命令执行，支持在浏览器里像 SecureCRT 一样操作设备

用法：
    terminal = WebTerminal(host='192.168.1.1', username='admin', password='admin')
    terminal.connect()
    output = terminal.execute('display version')
    terminal.disconnect()
"""

import paramiko
import time
import threading
import logging
import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

from utils.log_setup import setup_logger

logger = setup_logger("web_terminal", "terminal.log")


class WebTerminal:
    """
    Web 终端类
    通过 SSH 连接设备，执行命令，返回结果
    """

    def __init__(self, host, port=22, username='admin', password='', device_type='huawei', timeout=10):
        """
        初始化 Web 终端
        :param host: 设备 IP
        :param port: SSH 端口（默认 22）
        :param username: 用户名
        :param password: 密码
        :param timeout: 连接超时时间
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.client = None
        self.shell = None
        self.is_connected = False

    def connect(self):
        """
        建立 SSH 连接
        :return: True/False
        """
        try:
            # 创建 SSH 客户端
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # 连接设备
            logger.info(f"正在连接设备 {self.host}:{self.port}")
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.timeout,
                allow_agent=False,
                look_for_keys=False,
            )

            # 获取交互式 Shell
            self.shell = self.client.invoke_shell(term='xterm', width=200, height=50)
            self.is_connected = True

            # 等待设备响应（登录提示等）
            time.sleep(1)
            self._read_output()

            logger.info(f"设备 {self.host} 连接成功")
            return True

        except paramiko.AuthenticationException:
            logger.error(f"设备 {self.host} 认证失败：用户名或密码错误")
            return False
        except paramiko.SSHException as e:
            logger.error(f"设备 {self.host} SSH 连接失败：{e}")
            return False
        except Exception as e:
            logger.error(f"设备 {self.host} 连接异常：{e}")
            return False

    def disconnect(self):
        """断开 SSH 连接"""
        try:
            if self.shell:
                self.shell.close()
            if self.client:
                self.client.close()
            self.is_connected = False
            logger.info(f"设备 {self.host} 已断开连接")
        except Exception as e:
            logger.warning(f"断开连接时出错：{e}")

    def execute(self, command, wait_time=2):
        """
        执行命令并返回结果
        :param command: 要执行的命令
        :param wait_time: 等待设备响应的时间（秒）
        :return: 命令输出
        """
        if not self.is_connected:
            return "错误：未连接到设备"

        try:
            # 发送命令
            logger.info(f"执行命令：{command}")
            self.shell.send(command + '\n')

            # 等待设备响应
            time.sleep(wait_time)

            # 读取输出
            output = self._read_output()

            return output

        except Exception as e:
            logger.error(f"执行命令失败：{e}")
            return f"错误：{str(e)}"

    def _read_output(self):
        """读取 Shell 输出"""
        output = ""
        while self.shell.recv_ready():
            chunk = self.shell.recv(65535).decode('utf-8', errors='ignore')
            output += chunk
            time.sleep(0.1)
        return output

    def send_command(self, command):
        """
        发送命令（不等待响应）
        用于需要手动控制等待时间的场景
        """
        if not self.is_connected:
            return False

        try:
            self.shell.send(command + '\n')
            return True
        except Exception as e:
            logger.error(f"发送命令失败：{e}")
            return False

    def read_response(self, timeout=5):
        """
        读取响应（带超时）
        :param timeout: 超时时间（秒）
        :return: 输出内容
        """
        if not self.is_connected:
            return ""

        output = ""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self.shell.recv_ready():
                chunk = self.shell.recv(65535).decode('utf-8', errors='ignore')
                output += chunk
            else:
                time.sleep(0.1)

        return output

    def is_alive(self):
        """检查连接是否还活着"""
        if not self.is_connected or not self.client:
            return False

        try:
            # 尝试发送一个空包检查连接
            transport = self.client.get_transport()
            if transport and transport.is_active():
                return True
            return False
        except:
            return False


class TerminalManager:
    """
    终端管理器
    管理多个设备的终端连接
    """

    def __init__(self):
        # 存储活跃的终端连接 {session_id: WebTerminal}
        self.terminals = {}
        self._lock = threading.Lock()

    def create_terminal(self, session_id, host, port=22, username='admin', password='', timeout=10):
        """
        创建新的终端连接
        :param session_id: 会话 ID
        :param host: 设备 IP
        :param port: SSH 端口
        :param username: 用户名
        :param password: 密码
        :param timeout: 连接超时
        :return: WebTerminal 对象
        """
        with self._lock:
            # 如果已有连接，先断开
            if session_id in self.terminals:
                self.terminals[session_id].disconnect()

            # 创建新连接
            terminal = WebTerminal(host, port, username, password, timeout=timeout)
            if terminal.connect():
                self.terminals[session_id] = terminal
                return terminal
            return None

    def get_terminal(self, session_id):
        """获取终端连接"""
        with self._lock:
            return self.terminals.get(session_id)

    def execute_command(self, session_id, command, wait_time=2):
        """
        在指定终端执行命令
        :param session_id: 会话 ID
        :param command: 命令
        :param wait_time: 等待时间
        :return: 命令输出
        """
        terminal = self.get_terminal(session_id)
        if terminal:
            return terminal.execute(command, wait_time)
        return "错误：终端不存在"

    def close_terminal(self, session_id):
        """关闭终端连接"""
        with self._lock:
            if session_id in self.terminals:
                self.terminals[session_id].disconnect()
                del self.terminals[session_id]

    def close_all(self):
        """关闭所有终端连接"""
        with self._lock:
            for session_id, terminal in self.terminals.items():
                try:
                    terminal.disconnect()
                except:
                    pass
            self.terminals.clear()

    def get_active_sessions(self):
        """获取所有活跃会话"""
        with self._lock:
            sessions = []
            for session_id, terminal in self.terminals.items():
                sessions.append({
                    'session_id': session_id,
                    'host': terminal.host,
                    'is_connected': terminal.is_alive(),
                })
            return sessions


# 全局终端管理器实例
terminal_manager = TerminalManager()
