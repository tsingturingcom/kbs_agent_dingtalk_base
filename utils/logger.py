import logging
import os
import sys
from datetime import datetime

# 创建日志目录
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
os.makedirs(log_dir, exist_ok=True)

# 配置日志格式
log_file = os.path.join(log_dir, f'agent_{datetime.now().strftime("%Y%m%d")}.log')
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# 获取环境变量中设置的日志级别，默认为INFO
log_level_env = os.environ.get('BASEAGENT_LOG_LEVEL', 'INFO').upper()
log_levels = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}
console_log_level = log_levels.get(log_level_env, logging.INFO)
# 文件日志级别默认为WARNING，减少日志文件大小
file_log_level = log_levels.get(os.environ.get('BASEAGENT_FILE_LOG_LEVEL', 'WARNING').upper(), logging.WARNING)

# 创建logger
logger = logging.getLogger('baseagent')
logger.setLevel(logging.DEBUG)  # 设置为最低级别，让处理器决定

# 创建文件处理器
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setLevel(file_log_level)  # 文件日志级别默认更高
file_handler.setFormatter(logging.Formatter(log_format))
logger.addHandler(file_handler)

# 创建控制台处理器
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(console_log_level)  # 控制台日志级别可配置
console_handler.setFormatter(logging.Formatter(log_format))
logger.addHandler(console_handler)

# 新增：记录启动时的日志级别设置
logger.info(f"日志系统初始化: 控制台级别={log_level_env}, 文件级别={'WARNING' if file_log_level == logging.WARNING else os.environ.get('BASEAGENT_FILE_LOG_LEVEL', 'WARNING').upper()}")

def debug(msg, *args, **kwargs):
    """记录调试级别日志"""
    logger.debug(msg, *args, **kwargs)

def info(msg, *args, **kwargs):
    """记录信息级别日志"""
    logger.info(msg, *args, **kwargs)

def warning(msg, *args, **kwargs):
    """记录警告级别日志"""
    logger.warning(msg, *args, **kwargs)

def error(msg, *args, **kwargs):
    """记录错误级别日志"""
    logger.error(msg, *args, **kwargs)

def critical(msg, *args, **kwargs):
    """记录严重错误级别日志"""
    logger.critical(msg, *args, **kwargs) 