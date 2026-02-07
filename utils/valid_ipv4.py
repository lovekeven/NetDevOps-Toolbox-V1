def is_valid_ipv4(ip):
    # 第一步：先判断是否为空和是否是数字和点组成的
    if not ip or not ip.strip():
        return False, "IP地址不能为空"
    ip_stripped = ip.strip()
    for ip_str in ip_stripped:
        if not (ip_str.isdigit() or ip_str == "."):
            # not (a or b) ≠ not a or not b
            # not (a or b)
            # 翻译成人话：「字符是数字 或者 是点」这件事不成立 → 也就是「字符既不是数字，也不是点」。
            return False, f"IP地址含非法字符「{ip_str}」，仅允许数字和点"
    # 第二步：分成四段来判断，看每段是否符合要求
    ip_clean = ip_stripped.split(".")  # 这是得到了一个列表，元素是四段
    if len(ip_clean) != 4:
        return False, f"IP地址「{ip_stripped}」格式错误，需为4段（如192.168.1.1）"
    for ipx, ip_duan in enumerate(ip_clean):
        if not ip_duan.strip() or (len(ip_duan) > 1 and ip_duan.startswith("0")):
            return False, f"IP地址第{ipx+1}段格式错误（不能空/前置0）"
        # 第三步：判断每一段是否符合范围
        try:
            ip__duan = int(ip_duan)
            if ip__duan < 0 or ip__duan > 255:
                return False, f"IP地址第{ipx+1}段「{ip__duan}」超出范围（0~255）"
        except ValueError:
            return False, f"IP地址第{ipx+1}段「{ip_duan}」不是有效数字"
    return True, "IP地址合法"
