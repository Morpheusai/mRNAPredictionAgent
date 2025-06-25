import logging

from config import CONFIG_YAML

log_level = CONFIG_YAML["LOGGER"]["level"]

# 创建logger
logger = logging.getLogger("info_logger")
logger.handlers.clear()  # 清除已有handler
logger.propagate = False  # 防止向上传播到root logger
logger.setLevel(log_level)

# 创建控制台handler并设置格式
handler = logging.StreamHandler()  # 使用StreamHandler输出到终端
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# 添加handler到logger
logger.addHandler(handler)