import json  # 解析数据库的备份文件变为JSON格式给deepseek
import sys
import requests  # 发送请求
import logging
import time
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
# Python 从根目录开始找时，会「递归搜所有带__init__.py的文件夹」——__init__.py的唯一核心作用就是：告诉 Python“这个文件夹是合法
# 的包，可以被导入”
from db.database import db_manager

from utils.log_setup import setup_logger

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
        record = self.db.get_recent_backups(days=days)  # 返回的是列表的字典
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
            logger.error(f"报告内容生成失败，AI调用失败 {error_msg[:100]}")
            raise
    def get_deepseek_to_device_health(self,device_name = None,days = 7):
        logger.info(f"正在分析设备{device_name}近{days}天的健康状态...")
        if device_name is None:
            return "请指定要分析的设备名称"
        helthly_record = self.db.get_health_check_history(device_name=device_name,days=days)
        if not helthly_record:
            return f"设备{device_name}没有健康检查历史记录"
        prompt = f"""
        你是资深网络运维工程师，专注单台网络设备的健康分析与故障排查，分析精准、建议落地。
        请根据以下【{device_name}】的健康检查原始记录（JSON格式），生成一份单设备专属健康分析报告，内容简洁有深度，贴合实际运维排查场景。

        【{device_name} - 近{days}天健康检查原始记录】:
        {json.dumps(helthly_record, indent=2, ensure_ascii=False)}

        # 核心分析要求（仅单设备，必覆盖）
        1. 设备健康概况：统计检查总次数、健康/异常次数，计算健康率（保留2位小数）；
        2. 异常规律分析：提炼异常类型，统计高频异常；分析异常是否集中在特定时段、是否周期性出现；
        3. 关键异常详情：列出严重异常（连续异常/多次同类型异常），含异常时间、具体信息；
        4. 运维优化建议：给出2-3条针对性强的落地建议，贴合该设备的异常情况，拒绝空话。

        # 报告格式要求
        分模块简短表述，用项目符号/短句，专业简洁，检查时间统一按YYYY-MM-DD HH:MM显示。
        """     
        try:
            health_report = self.use_deepseek_api(prompt)
            logger.info("报告内容生成成功！")
            print(health_report)
            return health_report
        except Exception as e:
            error_msg = str(e)
            logger.error(f"报告内容生成失败，AI调用失败 {error_msg[:100]}")
            raise
    def get_deepseek_all_device_health_weekly(self, days=7):
            logger.info(f"正在分析所有设备近{days}天的健康状态，生成AI运维报告...")
            all_health_record = self.db.get_health_check_history(days=days)
            if not all_health_record:
                return f"近{days}天全网无设备健康检查记录，无法生成健康周报"
            
            # 全设备周报专属Prompt - 精简聚焦全网汇总、分层、高频问题、全局建议
            prompt = f"""
        你是10年+资深网络运维架构师，擅长全网设备健康状态汇总分析与运维周报编写，报告专业简洁、数据支撑充分、建议落地可执行。
        请根据以下【全网所有设备近{days}天健康检查原始记录（JSON格式）】，生成一份全网设备健康运维周报，贴合企业运维定期汇报场景，内容聚焦全局概况、问题汇总、优化建议。

        【全网设备 - 近{days}天健康检查原始记录】:
        {json.dumps(all_health_record, indent=2, ensure_ascii=False)}

        # 核心分析要求（全网汇总，必覆盖）
        1. 全网健康概况：统计涉及设备总数、健康检查总次数，计算全网整体健康率（保留2位小数）；统计健康/异常设备数、各状态检查次数及占比；
        2. 设备健康分层：按健康率分层（优秀≥95%、良好80%-95%、待关注＜80%），统计各层级设备数量及代表设备；列出健康率垫底3台异常频发设备；
        3. 全网异常汇总：提炼全网高频异常类型TOP3，统计各类型异常次数，做简单根因推断（贴合全网共性问题）；
        4. 运维优化建议：给出3条全网层面的落地优化建议，兼顾紧急性和可执行性，拒绝空话；
        5. 周报小结：用1-2句话总结全网健康状态，明确后续核心运维重点。

        # 报告格式要求（周报风格）
        分模块用二级标题+项目符号表述，专业简洁、重点突出，检查时间统一按YYYY-MM-DD HH:MM显示，适配运维口头/书面汇报。
        """
            # 保持和单设备一致的调试打印格式
            print("=" * 50 + "传给AI的【全网设备健康周报】Prompt" + "=" * 50)
            print(prompt)
            print("=" * 100)
            
            logger.info("正在生成全网设备健康AI周报....")
            try:
                health_report = self.use_deepseek_api(prompt)  # 复用原有AI调用方法
                logger.info("全网设备健康AI周报生成成功！")
                print(health_report)
                return health_report
            except Exception as e:
                error_msg = str(e)
                logger.error(f"全网健康报告生成失败，AI调用失败 {error_msg[:100]}")
                raise


deepseek_api = os.getenv("DEEPSEEK_API_KEY", "")
if deepseek_api:
    deepseek_assistant = ReportGenerator(deepseek_api)
else:

    deepseek_assistant = None
    logger.error("获取API key失败！")
