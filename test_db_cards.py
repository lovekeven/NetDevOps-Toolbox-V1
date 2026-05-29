import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from db.database import DatabaseManager

db_manager = DatabaseManager()

try:
    cards = db_manager.get_all_physical_cards()
    print(f"数据库中共找到 {len(cards)} 张档案卡")
    print("-" * 60)
    
    for i, card in enumerate(cards):
        print(f"\n=== 档案卡 {i+1} ===")
        print(f"设备名: {card.get('name')}")
        print(f"IP地址: {card.get('ip_address')}")
        print(f"厂商: {card.get('vendor')}")
        print(f"版本: {card.get('version')[:50]}..." if card.get('version') and len(card.get('version')) > 50 else f"版本: {card.get('version')}")
        print(f"UP端口: {card.get('up_interfaces')}")
        print(f"DOWN端口: {card.get('down_interface')}")
        print(f"总端口: {card.get('total_interfaces')}")
        print(f"CPU使用率: {card.get('cpu_usage')}")
        print(f"内存使用率: {card.get('memory_usage')}")
        print(f"所有字段: {list(card.keys())}")
        
except Exception as e:
    print(f"查询失败: {e}")
finally:
    db_manager.close()
