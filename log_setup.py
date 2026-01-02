import sys
import os
import logging


def setup_logger(name=__name__, log_file="netdevops_toolbox.log"):
    logger = logging.getLogger(name)
    logger.propagate = False
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    LOG = "logs"
    os.makedirs(LOG, exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(LOG, log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    console_Formatter = logging.Formatter("%(levelname)s-%(message)s")
    console_handler.setFormatter(console_Formatter)

    file_Formatter = logging.Formatter("%(asctime)s-%(name)s-%(levelname)s-%(message)s", datefmt="%Y%m%d-%H%M%S")
    file_handler.setFormatter(file_Formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
