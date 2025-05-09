"""
持久化管理器工厂，根据配置选择使用SQLite或Supabase实现
"""

from utils import logger
from utils.config import config
from agent.core.persistence_manager import PersistenceManager
from agent.core.supabase_persistence_manager import SupabasePersistenceManager

def get_persistence_manager():
    """
    根据配置返回合适的持久化管理器实例
    
    Returns:
        PersistenceManager或SupabasePersistenceManager的实例
    """
    try:
        database_type = config.config.get('database', 'database_type')
        
        if database_type == 'supabase':
            logger.info("使用Supabase作为数据存储后端")
            return SupabasePersistenceManager()
        else:
            logger.info("使用SQLite作为数据存储后端")
            return PersistenceManager()
    except Exception as e:
        logger.error(f"获取持久化管理器时出错: {str(e)}", exc_info=True)
        logger.info("默认使用SQLite作为数据存储后端")
        return PersistenceManager() 