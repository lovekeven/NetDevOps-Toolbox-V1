import json  # 解析数据库的备份文件变为JSON格式给deepseek
import requests  # 发送请求
import logging
import time
from database import db_manager
import os
from log_setup import setup_logger

logger = setup_logger("report_generator", "report_generator.log")


class ReportGenerator:
    def __init__(self, api_key):
        self.api_key = api_key
        self.deepseek_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        self.db = db_manager
        logger.info("智能报告生成器初始化完成")

    def use_deepseek_api(self, prompt):  # prompt迅速促使
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }  # Content-Type代表请求头的数据格式
        data = {
            "model": "glm-4.7",  # 模型名称，其他平台需更换
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,  # 控制创造性，0.0较保守，1.0更有创意
            "max_tokens": 10000,  # 限制回复长度
        }
        try:
            response = requests.post(
                self.deepseek_URL, headers=headers, json=data, timeout=200
            )  # 请求完毕之后返回一个Response对象
            # 相当于把HTTP回应报文封装到了Response对象里
            response.raise_for_status()
            logger.info("Deepseek API接口调用成功！")
            time.sleep(0.5)
            logger.info("正在解析返回数据......")
            result = response.json()
            report = result["choices"][0]["message"]["content"]
            logger.info("Deepseek返回结果解析成功！")
            return report.strip()
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            logger.error(f"Deepseek API接口调用失败 {error_msg[:100]}")
            raise
        except json.JSONDecodeError as e:
            error_msg = str(e)
            logger.error(f"解析JSON格式响应体失败 {error_msg[:100]}")
            raise
        except (KeyError, IndexError) as e:
            error_msg = str(e)
            logger.error(f"Deepseek返回结果解析失败 {error_msg[:100]}")
            raise

    def get_deepseek_content(self, days=7):
        logger.info(f"正在分析近{days}天的备份记录")
        record = self.db.get_recent_backups(limit=50)
        if not record:
            return "没有备份历史记录"
        prompt = f"""你是一名专业的网络运维工程师。请根据以下备份记录数据，生成一份简洁的运维摘要报告：

        【原始备份记录数据】（JSON格式）:
        {json.dumps(record, indent=2, ensure_ascii=False)}

        请用中文分析并总结，报告需包含以下部分：
        1.  **整体概况**：统计期内备份任务总数、成功率。
        2.  **设备活跃度**：备份最频繁的设备Top 3。
        3.  **问题发现**：列出所有失败的备份及其可能原因（根据error_message推断）。
        4.  **改进建议**：基于以上分析，给出1-2条具体的运维优化建议。

        报告要求：专业、清晰、直接，使用简洁的段落和列表，避免冗长。
        """
        print("=" * 50 + "传给AI的Prompt" + "=" * 50)
        print(prompt)
        print("=" * 100)
        # =================================================
        logger.info("正在生成报告内容....")
        try:
            backup_report = self.use_deepseek_api(prompt)
            logger.info("报告内容生成成功！")
            print(backup_report)
            return backup_report
        except Exception as e:
            error_msg = str(e)
            logger.error("报告内容生成失败，AI调用失败")
            raise


deepseek_api = os.getenv("DEEPSEEK_API_KEY", "")
if deepseek_api:
    deepseek_assistant = ReportGenerator(deepseek_api)
else:

    deepseek_assistant = None
    logger.error("获取API key失败！")
