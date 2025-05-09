import sqlite3
import uuid
import json
import threading
import os
from typing import List, Dict, Any, Optional
import datetime
from datetime import timezone

from utils import logger
from utils.config import config

# Use thread-local storage for database connections
db_local = threading.local()

# 定义数据库文件路径
DB_NAME = 'baseagent.db'
DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), DB_NAME)

def get_db():
    """Gets the database connection for the current thread."""
    if not hasattr(db_local, 'connection'):
        logger.debug(f"Creating new DB connection for thread {threading.get_ident()} to {DATABASE_PATH}")
        try:
            # Connect with check_same_thread=False for multithreaded access if needed,
            # but thread-local should handle most cases. Using default is safer.
            # Consider WAL mode for better concurrency if write contention is an issue.
            db_local.connection = sqlite3.connect(DATABASE_PATH, check_same_thread=True)
            db_local.connection.row_factory = sqlite3.Row
            # db_local.connection.execute("PRAGMA journal_mode=WAL;") # Optional: WAL mode
        except sqlite3.Error as e:
            logger.error(f"Database connection error to {DATABASE_PATH}: {e}", exc_info=True)
            raise
    return db_local.connection

def close_db(e=None):
    """Closes the database connection for the current thread."""
    connection = getattr(db_local, 'connection', None)
    if connection is not None:
        logger.debug(f"Closing DB connection for thread {threading.get_ident()}")
        connection.close()
        db_local.connection = None

class PersistenceManager:
    """负责与数据库交互，管理线程和消息的持久化。"""

    def __init__(self):
        """初始化，确保数据库和表已创建。"""
        self._init_db_schema()

    def _init_db_schema(self):
        """初始化数据库表结构，优化设计"""
        db = get_db()
        try:
            cursor = db.cursor()
            
            # 创建 threads 表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                robot_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                conversation_type TEXT NOT NULL, -- '单聊' 或 '群聊'
                conversation_id TEXT NOT NULL,   -- 群ID或单聊ID
                last_active_at TEXT,             -- 最后活跃时间
                group_name TEXT,                 -- 仅对群聊有效，最新群名称
                user_id TEXT,                    -- 仅对单聊有效，用户ID
                user_nick TEXT,                  -- 仅对单聊有效，用户昵称
                metadata TEXT                    -- 附加信息
            )
            """)
            
            # 创建 messages 表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                robot_code TEXT NOT NULL,
                role TEXT NOT NULL,              -- 'user' 或 'assistant'
                content TEXT NOT NULL,           -- 消息内容
                created_at TEXT NOT NULL,        -- 创建时间
                conversation_id TEXT NOT NULL,   -- 群ID或单聊ID
                conversation_type TEXT NOT NULL, -- '单聊' 或 '群聊'
                sender_id TEXT,                  -- 发送者ID (用户消息)
                sender_nick TEXT,                -- 发送者昵称 (用户消息)
                group_name TEXT,                 -- 群名称 (群聊消息)
                metadata TEXT,                   -- 其他元数据，避免重复存储已有字段
                FOREIGN KEY (thread_id) REFERENCES threads(thread_id)
            )
            """)
            
            # 创建 group_info 表 - 存储群id和群标题
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_info (
                conversation_id TEXT PRIMARY KEY, -- 群ID
                group_name TEXT NOT NULL,        -- 群名称
                robot_code TEXT NOT NULL,        -- 机器人编码
                updated_at TEXT NOT NULL,        -- 更新时间
                metadata TEXT                    -- 附加信息
            )
            """)
            
            # 创建 bot_groups 表 - 存储机器人所在的群id
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                robot_code TEXT NOT NULL,        -- 机器人编码
                conversation_id TEXT NOT NULL,   -- 群ID
                joined_at TEXT NOT NULL,         -- 加入时间
                metadata TEXT,                   -- 附加信息
                UNIQUE(robot_code, conversation_id)
            )
            """)
            
            # 创建索引提高查询效率
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_thread_created ON messages (thread_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id, conversation_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages (sender_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_threads_conversation ON threads (conversation_id, conversation_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_threads_robot ON threads (robot_code)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_info_robot ON group_info (robot_code)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_groups_robot ON bot_groups (robot_code)")
            
            db.commit()
            logger.info("数据库表结构初始化/验证完成。")
        except sqlite3.Error as e:
            logger.error(f"初始化数据库表结构时出错: {e}", exc_info=True)
            db.rollback()

    def add_new_thread(self, thread_id: str, created_at: str, metadata: Optional[Dict] = None) -> None:
        """添加新线程记录，优化数据结构"""
        db = get_db()
        try:
            # 提取关键字段
            robot_code = metadata.get("robot_code", "unknown")
            conversation_type = metadata.get("conversation_type", "未知")
            conversation_id = metadata.get("conversation_id", "")
            
            # 根据会话类型提取相关字段
            group_name = None
            user_id = None
            user_nick = None
            
            if conversation_type == "群聊":
                group_name = metadata.get("group_name", "未知群聊")
            elif conversation_type == "单聊":
                user_id = metadata.get("user_id", "")
                user_nick = metadata.get("user_nick", "未知用户")
            
            # 剩余的元数据转换为JSON
            remaining_metadata = {k: v for k, v in metadata.items() 
                                if k not in ["robot_code", "conversation_type", "conversation_id", 
                                            "group_name", "user_id", "user_nick"]}
            metadata_json = json.dumps(remaining_metadata) if remaining_metadata else None
            
            db.execute(
                """INSERT INTO threads 
                   (thread_id, robot_code, created_at, conversation_type, conversation_id, 
                    last_active_at, group_name, user_id, user_nick, metadata) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (thread_id, robot_code, created_at, conversation_type, conversation_id,
                 created_at, group_name, user_id, user_nick, metadata_json)
            )
            db.commit()
            logger.debug(f"新线程记录已添加: {thread_id} ({conversation_type})")
        except sqlite3.Error as e:
            logger.error(f"添加线程 {thread_id} 到数据库时出错: {e}", exc_info=True)
            db.rollback()

    def update_thread_last_active(self, thread_id: str, timestamp: str) -> bool:
        """更新线程最后活跃时间"""
        db = get_db()
        try:
            db.execute(
                "UPDATE threads SET last_active_at = ? WHERE thread_id = ?",
                (timestamp, thread_id)
            )
            db.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"更新线程 {thread_id} 活跃时间时出错: {e}", exc_info=True)
            db.rollback()
            return False

    def add_message(self, message: Dict[str, Any]) -> None:
        """添加消息记录，优化数据结构"""
        db = get_db()
        required_keys = ["message_id", "thread_id", "role", "content", "created_at"]
        if not all(key in message for key in required_keys):
            logger.error(f"尝试添加的消息缺少必要字段: {message}")
            return
        
        metadata = message.get("metadata", {})
        
        try:
            # 提取关键字段
            robot_code = metadata.get("robot_code", "unknown")
            conversation_type = metadata.get("conversation_type", "未知")
            conversation_id = metadata.get("conversation_id", "")
            sender_id = metadata.get("sender_id", metadata.get("user_id", ""))
            sender_nick = metadata.get("sender_nick", "")
            group_name = metadata.get("group_name", "")
            
            # 剩余的元数据转换为JSON
            remaining_metadata = {k: v for k, v in metadata.items() 
                                if k not in ["robot_code", "conversation_type", "conversation_id", 
                                           "sender_id", "sender_nick", "group_name", "user_id"]}
            metadata_json = json.dumps(remaining_metadata) if remaining_metadata else None
            
            # 添加消息记录
            db.execute(
                """INSERT INTO messages 
                   (message_id, thread_id, robot_code, role, content, created_at,
                    conversation_id, conversation_type, sender_id, sender_nick, group_name, metadata) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (message["message_id"], message["thread_id"], robot_code, message["role"], 
                 message["content"], message["created_at"], conversation_id, conversation_type,
                 sender_id, sender_nick, group_name, metadata_json)
            )
            
            # 更新线程最后活跃时间
            self.update_thread_last_active(message["thread_id"], message["created_at"])
            
            db.commit()
            logger.debug(f"消息 {message['message_id']} 已添加至线程 {message['thread_id']}")
        except sqlite3.Error as e:
            logger.error(f"添加消息 {message.get('message_id', '?')} 到数据库时出错: {e}", exc_info=True)
            db.rollback()

    def get_messages(self, thread_id: str, limit: Optional[int] = None, before_timestamp: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取线程消息，优化返回格式"""
        db = get_db()
        try:
            query = """SELECT * FROM messages WHERE thread_id = ?"""
            params = [thread_id]
            
            if before_timestamp:
                query += " AND created_at < ?"
                params.append(before_timestamp)
                
            query += " ORDER BY created_at DESC"
            
            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor = db.execute(query, tuple(params))
            messages_raw = cursor.fetchall()
            
            # 处理结果
            messages = []
            for row in reversed(messages_raw):  # 按时间顺序返回
                msg_dict = dict(row)
                
                # 处理元数据
                if msg_dict.get('metadata'):
                    try:
                        msg_dict['metadata'] = json.loads(msg_dict['metadata'])
                    except json.JSONDecodeError:
                        logger.warning(f"无法解析消息 {msg_dict['message_id']} 的元数据")
                        msg_dict['metadata'] = {}
                else:
                    msg_dict['metadata'] = {}
                    
                messages.append(msg_dict)
                
            return messages
        except sqlite3.Error as e:
            logger.error(f"获取线程 {thread_id} 消息时出错: {e}", exc_info=True)
            return []

    def get_all_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """(源自 utils.database.get_all_messages) 获取线程所有消息。"""
        return self.get_messages(thread_id, limit=None)

    def get_messages_after_timestamp(self, thread_id: str, timestamp: str) -> List[Dict[str, Any]]:
        """获取指定时间戳之后的消息，支持新字段"""
        db = get_db()
        try:
            query = """SELECT message_id, thread_id, role, content, created_at, 
                     conversation_id, conversation_type, metadata 
                     FROM messages WHERE thread_id = ? AND created_at > ? ORDER BY created_at ASC"""
            params = (thread_id, timestamp)
            cursor = db.execute(query, params)
            messages_raw = cursor.fetchall()
            messages = []
            for row in messages_raw:
                msg_dict = dict(row)
                if msg_dict.get('metadata'):
                    try: msg_dict['metadata'] = json.loads(msg_dict['metadata'])
                    except json.JSONDecodeError: msg_dict['metadata'] = {}
                else: msg_dict['metadata'] = {}
                messages.append(msg_dict)
            return messages
        except sqlite3.Error as e:
            logger.error(f"获取线程 {thread_id} 在 {timestamp} 之后消息时出错: {e}", exc_info=True)
            return []

    def get_last_summary_timestamp(self, thread_id: str) -> Optional[str]:
        """(源自 utils.database.get_last_summary_timestamp) 获取最后一条摘要消息的时间戳。"""
        db = get_db()
        try:
            # Using JSON extract operator ->> for potential index usage
            query = "SELECT MAX(created_at) FROM messages WHERE thread_id = ? AND json_extract(metadata, '$.is_summary') = 1"
            cursor = db.execute(query, (thread_id,))
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
        except sqlite3.Error as e:
            # Handle cases where json_extract might not be available or fails
            if "no such function: json_extract" in str(e):
                logger.warning("json_extract not available, falling back to slower metadata query.")
                try:
                    query_fallback = "SELECT MAX(created_at) FROM messages WHERE thread_id = ? AND metadata LIKE '%\"is_summary\": true%'"
                    cursor = db.execute(query_fallback, (thread_id,))
                    result = cursor.fetchone()
                    return result[0] if result and result[0] else None
                except sqlite3.Error as e_fallback:
                     logger.error(f"获取线程 {thread_id} 最后摘要时间戳时出错 (fallback): {e_fallback}", exc_info=True)
            else:
                 logger.error(f"获取线程 {thread_id} 最后摘要时间戳时出错: {e}", exc_info=True)
            return None

    def get_thread_metadata(self, thread_id: str) -> Optional[Dict]:
        """获取线程的元数据"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT metadata FROM threads WHERE thread_id = ?",
                (thread_id,)
            )
            result = cursor.fetchone()
            if result:
                return json.loads(result[0])
            return None
        except Exception as e:
            logger.error(f"获取线程元数据时出错: {e}")
            return None
        finally:
            conn.close()
    
    def update_thread_metadata(self, thread_id: str, metadata: Dict) -> bool:
        """更新线程的元数据"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        try:
            metadata_json = json.dumps(metadata, ensure_ascii=False)
            cursor.execute(
                "UPDATE threads SET metadata = ? WHERE thread_id = ?",
                (metadata_json, thread_id)
            )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"更新线程元数据时出错: {e}")
            return False
        finally:
            conn.close()

    def update_group_name(self, thread_id: str, new_group_name: str) -> bool:
        """更新群聊名称"""
        db = get_db()
        try:
            # 更新线程表中的群名
            db.execute(
                "UPDATE threads SET group_name = ? WHERE thread_id = ?",
                (new_group_name, thread_id)
            )
            db.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"更新群聊 {thread_id} 名称时出错: {e}", exc_info=True)
            db.rollback()
            return False

    def get_thread_info(self, thread_id: str) -> Optional[Dict]:
        """获取线程完整信息"""
        db = get_db()
        try:
            cursor = db.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,))
            result = cursor.fetchone()
            
            if not result:
                return None
                
            thread_info = dict(result)
            
            # 处理元数据
            if thread_info.get('metadata'):
                try:
                    thread_info['metadata'] = json.loads(thread_info['metadata'])
                except json.JSONDecodeError:
                    logger.warning(f"无法解析线程 {thread_id} 的元数据")
                    thread_info['metadata'] = {}
            else:
                thread_info['metadata'] = {}
                
            return thread_info
        except sqlite3.Error as e:
            logger.error(f"获取线程 {thread_id} 信息时出错: {e}", exc_info=True)
            return None

    # 以下是群信息和机器人群组相关的方法
    
    def update_group_info(self, conversation_id: str, group_name: str, robot_code: str) -> bool:
        """更新或添加群聊信息
        
        Args:
            conversation_id: 群聊ID
            group_name: 群聊名称
            robot_code: 机器人编码
            
        Returns:
            bool: 操作是否成功
        """
        db = get_db()
        try:
            # 获取当前时间
            now = datetime.datetime.now(timezone.utc).isoformat()
            
            # 检查群信息是否已存在
            cursor = db.cursor()
            cursor.execute(
                "SELECT conversation_id FROM group_info WHERE conversation_id = ?",
                (conversation_id,)
            )
            existing = cursor.fetchone()
            
            if existing:
                # 更新现有记录
                db.execute(
                    "UPDATE group_info SET group_name = ?, updated_at = ? WHERE conversation_id = ?",
                    (group_name, now, conversation_id)
                )
                logger.debug(f"已更新群聊信息: {conversation_id} - '{group_name}'")
            else:
                # 添加新记录
                db.execute(
                    "INSERT INTO group_info (conversation_id, group_name, robot_code, updated_at, metadata) VALUES (?, ?, ?, ?, ?)",
                    (conversation_id, group_name, robot_code, now, None)
                )
                logger.debug(f"已添加新群聊信息: {conversation_id} - '{group_name}'")
            
            db.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"更新群聊信息时出错: {e}", exc_info=True)
            db.rollback()
            return False
    
    def get_group_info(self, conversation_id: str) -> Optional[Dict]:
        """获取群聊信息
        
        Args:
            conversation_id: 群聊ID
            
        Returns:
            Dict or None: 群聊信息
        """
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute(
                "SELECT * FROM group_info WHERE conversation_id = ?",
                (conversation_id,)
            )
            row = cursor.fetchone()
            if row:
                # 将行转换为字典
                group_info = {key: row[key] for key in row.keys()}
                # 解析元数据
                if group_info.get("metadata"):
                    group_info["metadata"] = json.loads(group_info["metadata"])
                return group_info
            return None
        except sqlite3.Error as e:
            logger.error(f"获取群聊信息时出错: {e}", exc_info=True)
            return None
    
    def check_and_update_group_info(self, conversation_id: str, group_name: str, robot_code: str) -> bool:
        """检查并更新群聊信息（如果需要）
        
        如果群聊不存在或群名已变更，则更新群聊信息
        
        Args:
            conversation_id: 群聊ID
            group_name: 当前群聊名称
            robot_code: 机器人编码
            
        Returns:
            bool: 是否进行了更新
        """
        current_info = self.get_group_info(conversation_id)
        
        # 如果群聊不存在或群名已变更，更新群聊信息
        if not current_info or current_info.get("group_name") != group_name:
            self.update_group_info(conversation_id, group_name, robot_code)
            return True
        return False
    
    def add_bot_group(self, robot_code: str, conversation_id: str) -> bool:
        """添加机器人所在的群聊记录
        
        如果记录已存在，则忽略
        
        Args:
            robot_code: 机器人编码
            conversation_id: 群聊ID
            
        Returns:
            bool: 操作是否成功
        """
        db = get_db()
        try:
            # 获取当前时间
            now = datetime.datetime.now(timezone.utc).isoformat()
            
            # 检查记录是否已存在
            cursor = db.cursor()
            cursor.execute(
                "SELECT id FROM bot_groups WHERE robot_code = ? AND conversation_id = ?",
                (robot_code, conversation_id)
            )
            existing = cursor.fetchone()
            
            if not existing:
                # 添加新记录
                db.execute(
                    "INSERT INTO bot_groups (robot_code, conversation_id, joined_at, metadata) VALUES (?, ?, ?, ?)",
                    (robot_code, conversation_id, now, None)
                )
                logger.debug(f"已添加机器人群组记录: {robot_code} - {conversation_id}")
                db.commit()
                return True
            return True  # 记录已存在，视为成功
        except sqlite3.Error as e:
            logger.error(f"添加机器人群组记录时出错: {e}", exc_info=True)
            db.rollback()
            return False
    
    def get_bot_groups(self, robot_code: str) -> List[Dict]:
        """获取机器人所在的所有群聊
        
        Args:
            robot_code: 机器人编码
            
        Returns:
            List[Dict]: 机器人所在的群聊列表
        """
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute(
                """
                SELECT bg.*, gi.group_name 
                FROM bot_groups bg
                LEFT JOIN group_info gi ON bg.conversation_id = gi.conversation_id
                WHERE bg.robot_code = ?
                """,
                (robot_code,)
            )
            rows = cursor.fetchall()
            
            groups = []
            for row in rows:
                group = {key: row[key] for key in row.keys()}
                # 解析元数据
                if group.get("metadata"):
                    group["metadata"] = json.loads(group["metadata"])
                groups.append(group)
            
            return groups
        except sqlite3.Error as e:
            logger.error(f"获取机器人群组列表时出错: {e}", exc_info=True)
            return [] 