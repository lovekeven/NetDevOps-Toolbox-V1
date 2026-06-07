# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
把 NetDevOps-Toolbox 打包成 Windows exe

用法：
    pyinstaller build_windows.spec

打包完成后，exe 文件在 dist/NetDevOps-Toolbox/ 目录下
"""

import sys
import os

# 项目根目录
ROOT_DIR = os.path.dirname(os.path.abspath(SPEC))

block_cipher = None

# 主程序入口
a = Analysis(
    ['main.py'],  # 入口文件
    pathex=[ROOT_DIR],
    binaries=[],
    datas=[
        # 打包前端模板和静态文件
        ('web/templates', 'web/templates'),
        ('web/static', 'web/static'),
        # 打包配置文件
        ('config', 'config'),
        # 打包数据库（如果存在）
        ('db/*.db', 'db'),
    ],
    hiddenimports=[
        # Flask 相关
        'flask',
        'flask_socketio',
        'engineio.async_drivers.threading',
        # 数据库
        'sqlite3',
        # 网络库
        'netmiko',
        'nornir',
        'paramiko',
        'requests',
        # SNMP
        'pysnmp',
        # 其他
        'yaml',
        'apscheduler',
        'psutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的模块，减小体积
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 收集所有文件
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 生成 exe
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NetDevOps-Toolbox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 显示控制台，方便看日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='web/static/favicon.ico' if os.path.exists('web/static/favicon.ico') else None,
)

# 收集依赖文件
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NetDevOps-Toolbox',
)
