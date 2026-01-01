import os
import argparse
import sys

try:
    import backup
    import health_check

    MODULES_available = True
except Exception as e:
    print(f"错误：导入模块时出现未知错误 {e}")
    print(f"你可以通过命令行参数的方法来导入以上的两个模块！")
    MODULES_available = False


def run_backup(args):
    print("------调度备份功能------\n")
    print("=" * 60)
    cmd = ["python", "backup.py"]
    if args.all:
        cmd.append("--all")
    elif args.ip:
        if isinstance(args.ip, list):
            cmd.append("--ip")
            cmd.extend(args.ip)
        else:
            cmd.append("--ip")
            cmd.append(args.ip)
    elif args.file:
        cmd.append("--file")  # 这个以后可能是以后用户要加的命令
        cmd.append(args.file)
    print(f"执行命令：{" ".join(cmd)}")
    return os.system(" ".join(cmd))


def run_check_health(args):
    print("------调度检查健康功能------\n")
    print("=" * 60)
    cmd = ["python", "health_check.py"]
    if args.all:
        cmd.append("--all")
    elif args.ip:
        if isinstance(args.ip, list):
            cmd.append("--ip")
            cmd.extend(args.ip)
        else:
            cmd.append("--ip")
            cmd.append(args.ip)
    elif args.file:
        cmd.append("--file")
        cmd.append(args.file)
    print(f"执行命令：{' '.join(cmd)}")
    return os.system(" ".join(cmd))


def main():
    parse = argparse.ArgumentParser(
        description="网络运行设备工具箱 （NetDevOps-Toolbox-V1）-----统一调度中心",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用实例：
        %(prog)s --mode backup --all        #备份所有设备
        %(prog)s --mode backup --ip 192.168.91.111 192.168.91.112     #备份指定设备（支持多个）
        %(prog)s --mode check --all         #检查所有设备健康
        %(prog)s --mode check --ip 192.168.91.112 192.168.91.113      #检查指定设备健康（支持多个）
        """,
    )
    parse.add_argument(
        "--mode", "-m", choices=["backup", "check"], required=True, help="选择模式：backup(备份) check(检查健康)"
    )
    target_group = parse.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--all", action="store_true", help="模式：指定所有设备（检查或者备份）")
    target_group.add_argument("--ip", type=str, nargs="+", help="模式：指定设备（检查或者备份）")
    args = parse.parse_args()
    if args.mode == "backup":
        exit_code = run_backup(args)
    elif args.mode == "check":
        exit_code = run_check_health(args)
    else:
        exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
