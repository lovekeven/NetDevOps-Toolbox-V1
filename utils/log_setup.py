import sys
import os
import logging
import io


def setup_logger(name=__name__, log_file="netdevops_toolbox.log"):
    logger = logging.getLogger(name)
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        # 你有没有笔（处理器）
        return logger
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(LOG_DIR, exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(LOG_DIR, log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    console_Formatter = logging.Formatter("%(levelname)s-%(message)s")
    console_handler.setFormatter(console_Formatter)

    file_Formatter = logging.Formatter("%(asctime)s-%(name)s-%(levelname)s-%(message)s", datefmt="%Y%m%d-%H%M%S")
    file_handler.setFormatter(file_Formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
