"""
使用Supabase作为数据库后端的持久化管理器
"""
import json
import uuid
from typing import List, Dict, Any, Optional
import datetime
from datetime import timezone

from utils import logger
from utils.config import config
from supabase import create_client

class SupabasePersistenceManager:
    """使用Supabase作为数据库，管理线程和消息的持久化。"""

    def __init__(self):
        """初始化，连接到Supabase并确保表已创建。"""
        self.supabase_url = config.config.get('supabase', 'supabase_url')
        self.supabase_key = config.config.get('supabase', 'supabase_key')
        self.threads_table = config.config.get('supabase', 'supabase_threads_table')
        self.messages_table = config.config.get('supabase', 'supabase_messages_table')
        
        # 初始化Supabase客户端
        try:
            self.supabase = create_client(self.supabase_url, self.supabase_key)
            logger.info("已成功连接到Supabase")
            
            # 检查是否需要自动创建表
            if config.config.has_option('supabase', 'auto_create_tables') and config.config.getboolean('supabase', 'auto_create_tables'):
                self._ensure_tables_exist()
        except Exception as e:
            logger.error(f"连接Supabase时出错: {str(e)}", exc_info=True)
            raise
    
    def _ensure_tables_exist(self):
        """确保必需的表存在，如果不存在则创建"""
        try:
            # 保存SQL脚本到临时文件
            sql_path = "create_tables.sql"
            create_tables_sql = """
            -- 创建线程表
            CREATE TABLE IF NOT EXISTS public.threads (
                thread_id TEXT PRIMARY KEY,
                robot_code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                conversation_type TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                last_active_at TEXT,
                group_name TEXT,
                user_id TEXT,
                user_nick TEXT,
                metadata JSONB
            );
            
            -- 创建消息表
            CREATE TABLE IF NOT EXISTS public.messages (
                message_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL REFERENCES public.threads(thread_id),
                robot_code TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                conversation_type TEXT NOT NULL,
                sender_id TEXT,
                sender_nick TEXT,
                group_name TEXT,
                metadata JSONB
            );
            
            -- 创建群信息表
            CREATE TABLE IF NOT EXISTS public.group_info (
                conversation_id TEXT PRIMARY KEY,
                group_name TEXT NOT NULL,
                robot_code TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata JSONB
            );
            
            -- 创建机器人群组表
            CREATE TABLE IF NOT EXISTS public.bot_groups (
                id SERIAL PRIMARY KEY,
                robot_code TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                metadata JSONB,
                UNIQUE(robot_code, conversation_id)
            );
            
            -- 创建索引提高查询效率
            CREATE INDEX IF NOT EXISTS idx_messages_thread_created ON public.messages (thread_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_messages_conversation ON public.messages (conversation_id, conversation_type);
            CREATE INDEX IF NOT EXISTS idx_messages_sender ON public.messages (sender_id);
            CREATE INDEX IF NOT EXISTS idx_threads_conversation ON public.threads (conversation_id, conversation_type);
            CREATE INDEX IF NOT EXISTS idx_threads_robot ON public.threads (robot_code);
            CREATE INDEX IF NOT EXISTS idx_group_info_robot ON public.group_info (robot_code);
            CREATE INDEX IF NOT EXISTS idx_bot_groups_robot ON public.bot_groups (robot_code);
            """
            
            with open(sql_path, "w") as f:
                f.write(create_tables_sql)
            
            # 获取当前工作目录
            import os
            current_dir = os.path.dirname(os.path.abspath(__file__))
            supabase_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))), "supabase-docker")
            
            # 尝试通过Docker执行SQL
            try:
                import subprocess
                
                # 复制SQL文件到容器
                copy_cmd = f"docker cp {sql_path} supabase-db:/tmp/create_tables.sql"
                subprocess.run(copy_cmd, shell=True, check=True)
                
                # 执行SQL
                exec_cmd = f"docker-compose -f {os.path.join(supabase_dir, 'docker-compose.yml')} exec -T db psql -U postgres -d postgres -f /tmp/create_tables.sql"
                result = subprocess.run(exec_cmd, shell=True, check=True, capture_output=True)
                
                logger.info(f"表创建结果: {result.stdout.decode('utf-8')}")
            except subprocess.CalledProcessError as e:
                logger.error(f"执行Docker命令时出错: {e}")
                logger.error(f"错误输出: {e.stderr.decode('utf-8') if e.stderr else 'None'}")
                
                # 如果Docker方式失败，尝试使用REST API
                self._try_create_tables_via_rest()
            finally:
                # 删除临时SQL文件
                if os.path.exists(sql_path):
                    os.remove(sql_path)
                    
            logger.info("必要的表已创建或已存在")
        except Exception as e:
            logger.error(f"创建表时出错: {str(e)}", exc_info=True)
    
    def _try_create_tables_via_rest(self):
        """尝试通过REST API创建表"""
        try:
            # 使用service_role密钥
            service_role_key = config.config.get('supabase', 'supabase_service_role_key')
            admin_supabase = create_client(self.supabase_url, service_role_key)
            
            # 尝试创建threads表
            try:
                admin_supabase.table("threads").select("count(*)").limit(1).execute()
                logger.info("Threads表已存在")
            except Exception:
                logger.info("创建threads表...")
                # 直接使用REST API创建表
                admin_supabase.table("threads").insert({
                    "thread_id": "test",
                    "robot_code": "test",
                    "created_at": datetime.datetime.now(timezone.utc).isoformat(),
                    "conversation_type": "test",
                    "conversation_id": "test"
                }).execute()
                
                # 删除测试数据
                admin_supabase.table("threads").delete().eq("thread_id", "test").execute()
            
            # 尝试创建messages表
            try:
                admin_supabase.table("messages").select("count(*)").limit(1).execute()
                logger.info("Messages表已存在")
            except Exception:
                logger.info("创建messages表...")
                # 直接使用REST API创建表
                admin_supabase.table("messages").insert({
                    "message_id": "test",
                    "thread_id": "test",
                    "robot_code": "test",
                    "role": "test",
                    "content": "test",
                    "created_at": datetime.datetime.now(timezone.utc).isoformat(),
                    "conversation_id": "test",
                    "conversation_type": "test"
                }).execute()
                
                # 删除测试数据
                admin_supabase.table("messages").delete().eq("message_id", "test").execute()
        except Exception as e:
            logger.error(f"通过REST API创建表失败: {str(e)}", exc_info=True)

    def add_new_thread(self, thread_id: str, created_at: str, metadata: Optional[Dict] = None) -> None:
        """添加新线程记录"""
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
            
            # 准备Supabase数据
            thread_data = {
                "thread_id": thread_id,
                "robot_code": robot_code,
                "created_at": created_at,
                "conversation_type": conversation_type,
                "conversation_id": conversation_id,
                "last_active_at": created_at,
                "group_name": group_name,
                "user_id": user_id,
                "user_nick": user_nick,
                "metadata": metadata
            }
            
            # 添加到Supabase
            result = self.supabase.table(self.threads_table).insert(thread_data).execute()
            
            # 检查结果
            if hasattr(result, 'error') and result.error:
                logger.error(f"添加线程到Supabase时出错: {result.error}")
                return
                
            logger.debug(f"新线程记录已添加到Supabase: {thread_id} ({conversation_type})")
        except Exception as e:
            logger.error(f"添加线程 {thread_id} 到Supabase时出错: {str(e)}", exc_info=True)

    def update_thread_last_active(self, thread_id: str, timestamp: str) -> bool:
        """更新线程最后活跃时间"""
        try:
            result = self.supabase.table(self.threads_table)\
                .update({"last_active_at": timestamp})\
                .eq("thread_id", thread_id)\
                .execute()
            
            if hasattr(result, 'error') and result.error:
                logger.error(f"更新线程活跃时间时出错: {result.error}")
                return False
                
            return True
        except Exception as e:
            logger.error(f"更新线程 {thread_id} 活跃时间时出错: {str(e)}", exc_info=True)
            return False

    def add_message(self, message: Dict[str, Any]) -> None:
        """添加消息记录"""
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
            
            # 准备Supabase数据
            message_data = {
                "message_id": message["message_id"],
                "thread_id": message["thread_id"],
                "robot_code": robot_code,
                "role": message["role"],
                "content": message["content"],
                "created_at": message["created_at"],
                "conversation_id": conversation_id,
                "conversation_type": conversation_type,
                "sender_id": sender_id,
                "sender_nick": sender_nick,
                "group_name": group_name,
                "metadata": metadata
            }
            
            # 添加到Supabase
            result = self.supabase.table(self.messages_table).insert(message_data).execute()
            
            # 检查结果
            if hasattr(result, 'error') and result.error:
                logger.error(f"添加消息到Supabase时出错: {result.error}")
                return
            
            # 更新线程最后活跃时间
            self.update_thread_last_active(message["thread_id"], message["created_at"])
            
            logger.debug(f"消息 {message['message_id']} 已添加至Supabase线程 {message['thread_id']}")
        except Exception as e:
            logger.error(f"添加消息到Supabase时出错: {str(e)}", exc_info=True)

    def get_messages(self, thread_id: str, limit: Optional[int] = None, before_timestamp: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取指定线程的消息历史"""
        try:
            query = self.supabase.table(self.messages_table)\
                .select('*')\
                .eq('thread_id', thread_id)
            
            if before_timestamp:
                query = query.lt('created_at', before_timestamp)
            
            query = query.order('created_at', desc=True)
            
            if limit:
                query = query.limit(limit)
                
            result = query.execute()
            
            if hasattr(result, 'error') and result.error:
                logger.error(f"获取消息时出错: {result.error}")
                return []
                
            # 确保结果格式正确
            messages = result.data if hasattr(result, 'data') else []
            
            # 转换消息格式与原SQLite版本保持一致
            formatted_messages = []
            for msg in messages:
                formatted_msg = {
                    "message_id": msg.get("message_id"),
                    "thread_id": msg.get("thread_id"),
                    "role": msg.get("role"),
                    "content": msg.get("content"),
                    "created_at": msg.get("created_at"),
                    "metadata": msg.get("metadata", {})
                }
                formatted_messages.append(formatted_msg)
                
            return formatted_messages
        except Exception as e:
            logger.error(f"获取线程 {thread_id} 的消息时出错: {str(e)}", exc_info=True)
            return []

    def get_all_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """获取线程的所有消息"""
        return self.get_messages(thread_id)

    def get_messages_after_timestamp(self, thread_id: str, timestamp: str) -> List[Dict[str, Any]]:
        """获取指定时间戳之后的消息"""
        try:
            result = self.supabase.table(self.messages_table)\
                .select('*')\
                .eq('thread_id', thread_id)\
                .gt('created_at', timestamp)\
                .order('created_at')\
                .execute()
                
            if hasattr(result, 'error') and result.error:
                logger.error(f"获取消息时出错: {result.error}")
                return []
                
            # 确保结果格式正确
            messages = result.data if hasattr(result, 'data') else []
            
            # 转换消息格式
            formatted_messages = []
            for msg in messages:
                formatted_msg = {
                    "message_id": msg.get("message_id"),
                    "thread_id": msg.get("thread_id"),
                    "role": msg.get("role"),
                    "content": msg.get("content"),
                    "created_at": msg.get("created_at"),
                    "metadata": msg.get("metadata", {})
                }
                formatted_messages.append(formatted_msg)
                
            return formatted_messages
        except Exception as e:
            logger.error(f"获取线程 {thread_id} 的消息时出错: {str(e)}", exc_info=True)
            return []

    def get_thread_metadata(self, thread_id: str) -> Optional[Dict]:
        """获取线程元数据"""
        try:
            result = self.supabase.table(self.threads_table)\
                .select('metadata')\
                .eq('thread_id', thread_id)\
                .execute()
                
            if hasattr(result, 'error') and result.error:
                logger.error(f"获取线程元数据时出错: {result.error}")
                return None
                
            # 检查是否有数据
            if not result.data or len(result.data) == 0:
                return None
                
            return result.data[0].get('metadata', {})
        except Exception as e:
            logger.error(f"获取线程 {thread_id} 的元数据时出错: {str(e)}", exc_info=True)
            return None

    def update_thread_metadata(self, thread_id: str, metadata: Dict) -> bool:
        """更新线程元数据"""
        try:
            result = self.supabase.table(self.threads_table)\
                .update({"metadata": metadata})\
                .eq("thread_id", thread_id)\
                .execute()
            
            if hasattr(result, 'error') and result.error:
                logger.error(f"更新线程元数据时出错: {result.error}")
                return False
                
            return True
        except Exception as e:
            logger.error(f"更新线程 {thread_id} 的元数据时出错: {str(e)}", exc_info=True)
            return False

    def update_group_name(self, thread_id: str, new_group_name: str) -> bool:
        """更新群组名称"""
        try:
            result = self.supabase.table(self.threads_table)\
                .update({"group_name": new_group_name})\
                .eq("thread_id", thread_id)\
                .execute()
            
            if hasattr(result, 'error') and result.error:
                logger.error(f"更新群组名称时出错: {result.error}")
                return False
                
            return True
        except Exception as e:
            logger.error(f"更新线程 {thread_id} 的群组名称时出错: {str(e)}", exc_info=True)
            return False

    def get_thread_info(self, thread_id: str) -> Optional[Dict]:
        """获取线程信息"""
        try:
            result = self.supabase.table(self.threads_table)\
                .select('*')\
                .eq('thread_id', thread_id)\
                .execute()
                
            if hasattr(result, 'error') and result.error:
                logger.error(f"获取线程信息时出错: {result.error}")
                return None
                
            # 检查是否有数据
            if not result.data or len(result.data) == 0:
                return None
                
            return result.data[0]
        except Exception as e:
            logger.error(f"获取线程 {thread_id} 的信息时出错: {str(e)}", exc_info=True)
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
        try:
            # 获取当前时间
            now = datetime.datetime.now(timezone.utc).isoformat()
            
            # 检查群信息是否已存在
            result = self.supabase.table("group_info").select("*").eq("conversation_id", conversation_id).execute()
            existing = result.data
            
            if existing:
                # 更新现有记录
                self.supabase.table("group_info").update({
                    "group_name": group_name,
                    "updated_at": now
                }).eq("conversation_id", conversation_id).execute()
                logger.debug(f"已更新群聊信息: {conversation_id} - '{group_name}'")
            else:
                # 添加新记录
                self.supabase.table("group_info").insert({
                    "conversation_id": conversation_id,
                    "group_name": group_name,
                    "robot_code": robot_code,
                    "updated_at": now,
                    "metadata": {}
                }).execute()
                logger.debug(f"已添加新群聊信息: {conversation_id} - '{group_name}'")
            
            return True
        except Exception as e:
            logger.error(f"更新群聊信息时出错: {e}", exc_info=True)
            return False
    
    def get_group_info(self, conversation_id: str) -> Optional[Dict]:
        """获取群聊信息
        
        Args:
            conversation_id: 群聊ID
            
        Returns:
            Dict or None: 群聊信息
        """
        try:
            result = self.supabase.table("group_info").select("*").eq("conversation_id", conversation_id).execute()
            
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
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
        try:
            # 获取当前时间
            now = datetime.datetime.now(timezone.utc).isoformat()
            
            # 检查记录是否已存在
            result = self.supabase.table("bot_groups").select("*").eq("robot_code", robot_code).eq("conversation_id", conversation_id).execute()
            existing = result.data
            
            if not existing or len(existing) == 0:
                # 添加新记录
                self.supabase.table("bot_groups").insert({
                    "robot_code": robot_code,
                    "conversation_id": conversation_id,
                    "joined_at": now,
                    "metadata": {}
                }).execute()
                logger.debug(f"已添加机器人群组记录: {robot_code} - {conversation_id}")
            
            return True
        except Exception as e:
            logger.error(f"添加机器人群组记录时出错: {e}", exc_info=True)
            return False
    
    def get_bot_groups(self, robot_code: str) -> List[Dict]:
        """获取机器人所在的所有群聊
        
        Args:
            robot_code: 机器人编码
            
        Returns:
            List[Dict]: 机器人所在的群聊列表
        """
        try:
            # 使用join查询，但Supabase需要使用函数链接的方式
            result = self.supabase.from_("bot_groups")\
                .select("*, group_info(group_name)")\
                .eq("robot_code", robot_code)\
                .execute()
            
            # 处理查询结果
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"获取机器人群组列表时出错: {e}", exc_info=True)
            return [] 