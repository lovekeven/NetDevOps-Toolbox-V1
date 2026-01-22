import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from utils.log_setup import setup_logger
import time
from typing import Tuple, Type, Callable, Any  # Callable表示可调用对象，可以被（）调用执行的对象
from functools import wraps  # functools这个模块中的 wraps 装饰器，他是下面装饰器的辅助装饰器，目的是保留原函数的信息

logger = setup_logger("retry_decorator.py", "retry_decorator.log")


def network_retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factors: float = 2.0,  # 退避因子让让后面的重试间隔按照一定比例递增，这个是底数，重试次数是指数
    exception_need_catch: Tuple[type[Exception], ...] = (Exception,),  # ... 不是「三个点字符串」，是 Python 内置对象
    # 三个点它在类型注解、Numpy 等场景中专门用于表示「任意长度」「省略」的含义，在 Tuple 注解中是固定用法。
):
    """
    智能重试装饰器工厂函数

    参数:
        max_retries: 最大重试次数（不包含第一次尝试）
        initial_delay: 首次重试前的延迟（秒）
        backoff_factor: 延迟倍增因子（用于指数退避）
        exceptions_to_catch: 需要捕获并触发重试的异常元组
    """

    def decorator(func):
        @wraps(func)  # @wraps(func) 是一个「带参数的装饰器」（func 是它接收的参数，指定要复制元信息的原函数）
        # 它的作用对象是装饰器内部的 wrapper 函数；
        def wrapper(
            *args, **kwargs
        ) -> Any:  # 单星号收集位置参数，解包是可迭代的对象，而双星号收集关键字参数，解包是只能是字典
            last_exception = None
            delay = initial_delay
            for attempt in range(max_retries + 1):
                try:
                    if attempt > 0:
                        logger.warning(
                            f"{delay:.1f}秒后进行第{attempt}次重试，请稍后...."
                        )  # delay是要格式化的变量，而：是
                        # 格式分隔符，.1f是浮点数格式化规则，保留一位小数
                        time.sleep(delay)
                        delay *= backoff_factors
                    return func(*args, **kwargs)  # 解包位置参数和关键字参数
                except exception_need_catch as e:
                    last_exception = e
                    logger.warning(f"{func.__name__} 尝试{attempt+1} / {max_retries+1}失败！{e}")
                    if attempt == max_retries:
                        logger.error(f"{func.__name__} 共尝试了{max_retries+1}次，终以失败告终，请检查相关配置")
                        raise
            return last_exception

        return wrapper

    return decorator


ssh_retry = network_retry(
    max_retries=2,
    initial_delay=2.0,
    backoff_factors=2.0,
    exception_need_catch=(Exception,),
)

api_retry = network_retry(
    max_retries=3, initial_delay=1.0, backoff_factors=1.5, exception_need_catch=(ConnectionError, TimeoutError)
)
