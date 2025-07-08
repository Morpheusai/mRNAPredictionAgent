import logging
import os
from config import CONFIG_YAML

log_level = CONFIG_YAML["LOGGER"]["level"]

# 直接写到当前目录下的 log 文件
log_path = "log"

# 创建logger
logger = logging.getLogger("info_logger")
logger.handlers.clear()  # 清除已有handler
logger.propagate = False  # 防止向上传播到root logger
logger.setLevel(log_level)

# 控制台输出
stream_handler = logging.StreamHandler()  # 使用StreamHandler输出到终端
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

# 文件输出到 log
file_handler = logging.FileHandler(log_path, encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)