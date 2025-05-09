import configparser
import os

class Config:
    def __init__(self):
        self.config = configparser.ConfigParser()
        
        # 查找配置文件的多个可能位置
        config_paths = [
            # 1. 环境变量指定的路径
            os.environ.get('BASEAGENT_CONFIG_PATH'),
            # 2. 当前工作目录
            os.path.join(os.getcwd(), 'config.ini'),
            # 3. 项目根目录 (utils目录的上层)
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.ini'),
            # 4. 用户主目录
            os.path.join(os.path.expanduser("~"), '.baseagent', 'config.ini')
        ]
        
        # 过滤掉None值并尝试每个路径
        config_found = False
        for path in [p for p in config_paths if p]:
            if os.path.exists(path):
                self.config.read(path, encoding='utf-8')
                print(f"已加载配置文件: {path}")
                config_found = True
                self.config_path = path
                break
        
        if not config_found:
            raise FileNotFoundError("无法找到配置文件config.ini，请确保它存在于项目目录中")
        
        # LLM配置
        self.API_ENDPOINT = self.config.get('LLM_CONFIG', 'api_endpoint')
        self.API_KEY = self.config.get('LLM_CONFIG', 'api_key')
        self.MODEL = self.config.get('LLM_CONFIG', 'model')
        self.TEMPERATURE = self.config.getfloat('LLM_CONFIG', 'temperature')
        self.MAX_TOKENS = self.config.getint('LLM_CONFIG', 'max_tokens')
        self.TOP_P = self.config.getfloat('LLM_CONFIG', 'top_p')
        self.FREQUENCY_PENALTY = self.config.getfloat('LLM_CONFIG', 'frequency_penalty')
        self.PRESENCE_PENALTY = self.config.getfloat('LLM_CONFIG', 'presence_penalty')
        self.N = self.config.getint('LLM_CONFIG', 'n')
        self.STREAM = self.config.getboolean('LLM_CONFIG', 'stream')
        self.CONTEXT_WINDOW = self.config.getint('LLM_CONFIG', 'context_window')
        self.HISTORY_TURNS = self.config.getint('LLM_CONFIG', 'history_turns')
        
        # 添加预留令牌配置
        if self.config.has_option('LLM_CONFIG', 'reserve_tokens'):
            self.RESERVE_TOKENS = self.config.getint('LLM_CONFIG', 'reserve_tokens')
        else:
            self.RESERVE_TOKENS = 5000  # 默认预留5000个令牌

# 全局配置实例
config = Config() 