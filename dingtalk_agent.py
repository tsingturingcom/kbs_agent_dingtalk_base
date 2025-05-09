"""
BaseAgent - 钉钉机器人与大语言模型集成
只处理单聊消息
"""

import os
import sys
import asyncio
import json
import time
import uuid
import datetime
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime, timezone

# 确保能够导入模块
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 导入自定义模块
from utils import logger
from utils.config import config
from utils.dingtalk_sender import DingTalkSender
from agent.core.llm_interface import LLMInterface
from agent.core.persistence_factory import get_persistence_manager
from agent.core.context_manager import ContextManager
from agent.core.prompts import get_system_prompt  # 导入提示词模块

# 导入钉钉SDK
from dingtalk_stream import AckMessage, DingTalkStreamClient
from dingtalk_stream.credential import Credential
from dingtalk_stream.handlers import CallbackHandler
from dingtalk_stream.chatbot import ChatbotMessage

class DingTalkAgent:
    """钉钉机器人主类，处理单聊消息并使用LLM回复"""
    
    def __init__(self):
        """初始化钉钉机器人"""
        # 初始化组件
        self.persistence_manager = get_persistence_manager()  # 使用工厂方法获取持久化管理器
        self.llm_interface = LLMInterface()
        self.context_manager = ContextManager()
        self.context_manager.set_llm_api_caller(self.llm_interface.call_llm_api)
        self.context_manager.set_persistence_manager(self.persistence_manager)
        self.sender = DingTalkSender()
        
        # 获取机器人编码
        self.robot_code = config.config.get('dingtalk_config', 'dingtalk_robot_code')
        
        # 获取token计数器
        try:
            self._count_tokens = self.context_manager.get_token_counter()
        except AttributeError:
            logger.error("ContextManager 未提供 get_token_counter。使用备用。")
            def _fallback(m, mdl): return sum(len(i.get("content","")) for i in m)
            self._count_tokens = _fallback
        
        # 从提示词模块获取系统提示词
        self.system_prompt = get_system_prompt()
        
    def startup(self):
        """启动并运行钉钉机器人"""
        logger.info("启动钉钉机器人...")
        
        # 创建钉钉消息处理器
        class MessageHandler(CallbackHandler):
            def __init__(self, agent):
                super().__init__()  # 确保调用父类初始化
                self.agent = agent
                # 获取机器人名称
                if config.config.has_option('dingtalk_config', 'robot_name'):
                    self.robot_name = config.config.get('dingtalk_config', 'robot_name')
                else:
                    self.robot_name = '基础助手'
            
            async def process(self, callback):
                """处理钉钉回调数据"""
                try:
                    # 解析回调数据
                    data = callback.data
                    logger.debug(f"接收到钉钉回调: {json.dumps(data, ensure_ascii=False)}")
                    
                    # 确保是文本消息
                    if 'text' not in data or 'senderStaffId' not in data:
                        logger.info("收到非文本消息，忽略。")
                        return AckMessage.STATUS_OK, "ignore: not a text message"
                    
                    # 提取消息内容
                    message_text = data.get('text', {}).get('content', '').strip()
                    sender_staff_id = data.get('senderStaffId')
                    sender_nick = data.get('senderNick', '未知用户')
                    conversation_id = data.get('conversationId')
                    conversation_type = data.get('conversationType')
                    
                    if not message_text or not sender_staff_id or not conversation_id:
                        logger.warning("收到的消息缺少必要字段，忽略。")
                        return AckMessage.STATUS_OK, "ignore: missing fields"
                    
                    # 获取机器人编码
                    robot_code = config.config.get('dingtalk_config', 'dingtalk_robot_code')
                    
                    # 处理单聊和群聊消息
                    if conversation_type == '1':  # 单聊
                        logger.info(f"收到来自 '{sender_nick}' ({sender_staff_id}) 的单聊消息: '{message_text[:50]}...'")
                        
                        # 生成会话线程ID
                        thread_id = f"{robot_code}_{sender_staff_id}"
                        
                        # 创建上下文信息
                        context_info = {
                            "user_id": sender_staff_id,
                            "user_nick": sender_nick,
                            "conversation_id": conversation_id,
                            "conversation_type": "单聊",
                            "robot_code": robot_code
                        }
                        
                        # 创建后台任务处理消息
                        asyncio.create_task(
                            self.agent.handle_text_message(
                                thread_id=thread_id,
                                conversation_id=conversation_id,
                                sender_staff_id=sender_staff_id,
                                sender_nick=sender_nick,
                                message_text=message_text,
                                context_info=context_info
                            )
                        )
                        
                        return AckMessage.STATUS_OK, "success (processing started)"
                    elif conversation_type == '2':  # 群聊
                        # 尝试获取群名称
                        group_name = data.get('conversationTitle', '未知群聊')
                        at_users = data.get('atUsers', [])
                        
                        # 清理消息中的@提及
                        clean_message = message_text
                        for at_user in at_users:
                            at_text = f"@{at_user.get('dingtalkNick', '')}"
                            clean_message = clean_message.replace(at_text, "").strip()
                        
                        logger.info(f"收到来自群聊 '{group_name}' 的消息，发送者: '{sender_nick}' ({sender_staff_id}): '{message_text[:50]}...'")
                        
                        # 生成群聊会话线程ID - 直接使用conversation_id
                        thread_id = conversation_id
                        
                        # 创建上下文信息
                        context_info = {
                            "user_id": sender_staff_id,
                            "user_nick": sender_nick,
                            "conversation_id": conversation_id,
                            "conversation_type": "群聊",
                            "group_name": group_name,
                            "robot_code": robot_code
                        }
                        
                        # 创建后台任务处理消息
                        asyncio.create_task(
                            self.agent.handle_group_message(
                                thread_id=thread_id,
                                conversation_id=conversation_id,
                                sender_staff_id=sender_staff_id,
                                sender_nick=sender_nick,
                                message_text=clean_message,
                                group_name=group_name,
                                context_info=context_info
                            )
                        )
                        
                        return AckMessage.STATUS_OK, "success (group processing started)"
                    else:
                        logger.info(f"收到未知类型的会话消息，忽略: {conversation_type}")
                        return AckMessage.STATUS_OK, "ignore: unknown conversation type"
                
                except Exception as e:
                    logger.error(f"处理钉钉消息时出错: {str(e)}", exc_info=True)
                    return AckMessage.STATUS_OK, "error during processing"
        
        # 获取钉钉机器人配置
        client_id = config.config.get('dingtalk_config', 'dingtalk_client_id')
        client_secret = config.config.get('dingtalk_config', 'dingtalk_client_secret')
        
        logger.info(f"配置钉钉Stream SDK (ClientID: {client_id})")
        credential = Credential(client_id, client_secret)
        client = DingTalkStreamClient(credential)
        
        # 创建处理器实例
        message_handler = MessageHandler(self)
        # 注册正确的消息主题 - ChatbotMessage.TOPIC
        client.register_callback_handler(ChatbotMessage.TOPIC, message_handler)
        
        logger.info("启动钉钉Stream连接...")
        # 直接启动，不使用await
        client.start_forever()
    
    async def handle_text_message(self, thread_id: str, conversation_id: str, sender_staff_id: str, sender_nick: str, message_text: str, context_info: dict = None):
        """处理单聊文本消息"""
        if not message_text:
            logger.warning(f"收到空消息，已忽略")
            return
        
        logger.info(f"处理单聊消息: '{message_text[:50]}...' 来自 {sender_nick} ({sender_staff_id})")
        
        # 检查是否存在线程，如果不存在则创建新线程
        thread_messages = self.persistence_manager.get_all_messages(thread_id)
        if not thread_messages:
            # 创建新线程
            logger.info(f"为用户 '{sender_staff_id}' 创建新线程: {thread_id}")
            self.persistence_manager.add_new_thread(
                thread_id,
                datetime.now(timezone.utc).isoformat(),
                {
                    "user_id": sender_staff_id, 
                    "user_nick": sender_nick, 
                    "conversation_type": "单聊",
                    "robot_code": self.robot_code,
                    "conversation_id": conversation_id
                }
            )
            
            # 发送欢迎消息
            await self.sender.send_markdown_to_user(
                sender_staff_id, 
                "👋 欢迎使用", 
                "**欢迎使用智能助手**\n\n我可以帮您解答问题、提供信息和协助您完成各种任务。请告诉我您需要什么帮助？"
            )
        
        # 添加用户消息到数据库
        self.persistence_manager.add_message({
            "message_id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "role": "user",
            "content": message_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "sender_nick": sender_nick, 
                "conversation_type": "单聊",
                "robot_code": self.robot_code,
                "conversation_id": conversation_id,
                "sender_id": sender_staff_id
            }
        })
        
        # 获取对话历史并生成回答
        try:
            # 获取带上下文的系统提示词
            dynamic_system_prompt = get_system_prompt(context_info=context_info)
            
            # 获取对话上下文（考虑token限制）
            messages = await self.context_manager.get_optimal_context(
                thread_id,
                dynamic_system_prompt,
                config.CONTEXT_WINDOW,
                model=config.MODEL
            )
            
            # 调用LLM获取回答
            logger.info(f"向LLM发送请求 (消息数: {len(messages)})")
            llm_response = await self.llm_interface.call_llm_api(
                messages=messages,
                purpose="生成回答"
            )
            
            # 提取回答内容
            if llm_response.get("role") == "error":
                # 处理错误情况
                error_message = llm_response.get("content", "生成回答时发生错误")
                logger.error(f"LLM错误: {error_message}")
                response_text = f"抱歉，我在处理您的请求时遇到了问题。请稍后再试。\n\n技术细节: {error_message}"
                # 发送错误消息
                await self.sender.send_markdown_to_user(
                    sender_staff_id,
                    "❌ 处理错误",
                    response_text
                )
            else:
                # 获取正常回答
                response_text = llm_response.get("content", "")
                logger.info(f"收到LLM回答: '{response_text[:50]}...'")
                
                # 将回答添加到数据库
                self.persistence_manager.add_message({
                    "message_id": str(uuid.uuid4()),
                    "thread_id": thread_id,
                    "role": "assistant",
                    "content": response_text,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "metadata": {
                        "conversation_type": "单聊",
                        "robot_code": self.robot_code,
                        "conversation_id": conversation_id
                    }
                })
                
                # 发送回答给用户
                await self.sender.send_markdown_to_user(
                    sender_staff_id,
                    "回复",  # 提供一个简短标题，不能为空
                    response_text
                )
                
        except Exception as e:
            logger.error(f"处理消息时出错: {str(e)}", exc_info=True)
            # 发送错误消息
            await self.sender.send_markdown_to_user(
                sender_staff_id,
                "❌ 系统错误",
                f"抱歉，处理您的请求时发生了系统错误。请稍后再试。"
            )
    
    async def handle_group_message(self, thread_id: str, conversation_id: str, sender_staff_id: str, 
                                  sender_nick: str, message_text: str, group_name: str, context_info: dict = None):
        """处理群聊文本消息"""
        if not message_text:
            logger.warning(f"收到空消息，已忽略")
            return
        
        logger.info(f"处理群聊消息: '{message_text[:50]}...' 来自 {sender_nick} ({sender_staff_id}) 在群 '{group_name}'")
        
        # 检查并更新群信息
        self.persistence_manager.check_and_update_group_info(conversation_id, group_name, self.robot_code)
        
        # 记录机器人所在的群
        self.persistence_manager.add_bot_group(self.robot_code, conversation_id)
        
        # 检查是否存在线程，如果不存在则创建新线程
        thread_messages = self.persistence_manager.get_all_messages(thread_id)
        if not thread_messages:
            # 创建新线程
            logger.info(f"为群聊 '{group_name}' 创建新线程: {thread_id}")
            self.persistence_manager.add_new_thread(
                thread_id,
                datetime.now(timezone.utc).isoformat(),
                {
                    "conversation_id": conversation_id,
                    "group_name": group_name,
                    "conversation_type": "群聊",
                    "robot_code": self.robot_code
                }
            )
        else:
            # 检查群名是否变更
            thread_info = self.persistence_manager.get_thread_info(thread_id)
            if thread_info and thread_info.get("group_name") != group_name:
                logger.info(f"更新群聊名称: '{thread_info.get('group_name')}' -> '{group_name}'")
                self.persistence_manager.update_group_name(thread_id, group_name)
        
        # 添加用户消息到数据库
        self.persistence_manager.add_message({
            "message_id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "role": "user",
            "content": message_text,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "sender_nick": sender_nick,
                "sender_id": sender_staff_id,
                "group_name": group_name,
                "conversation_type": "群聊",
                "robot_code": self.robot_code,
                "conversation_id": conversation_id
            }
        })
        
        # 获取对话历史并生成回答
        try:
            # 获取带上下文的系统提示词
            dynamic_system_prompt = get_system_prompt(context_info=context_info)
            
            # 获取对话上下文（考虑token限制）
            messages = await self.context_manager.get_optimal_context(
                thread_id,
                dynamic_system_prompt,
                config.CONTEXT_WINDOW,
                model=config.MODEL
            )
            
            # 调用LLM获取回答
            logger.info(f"向LLM发送群聊请求 (消息数: {len(messages)})")
            llm_response = await self.llm_interface.call_llm_api(
                messages=messages,
                purpose="生成群聊回答"
            )
            
            # 提取回答内容
            if llm_response.get("role") == "error":
                # 处理错误情况
                error_message = llm_response.get("content", "生成回答时发生错误")
                logger.error(f"LLM错误: {error_message}")
                response_text = f"抱歉 @{sender_nick}，我在处理您的请求时遇到了问题。请稍后再试。\n\n技术细节: {error_message}"
                # 发送错误消息
                await self.sender.send_markdown_to_group(
                    conversation_id,
                    "❌ 处理错误",
                    response_text
                )
            else:
                # 获取正常回答
                response_text = llm_response.get("content", "")
                logger.info(f"收到群聊LLM回答: '{response_text[:50]}...'")
                
                # 检查LLM回复是否已经包含@用户
                if response_text.startswith(f'@{sender_nick}'):
                    # 如果已经包含@，直接使用LLM的回答
                    formatted_response = response_text
                else:
                    # 否则添加@
                    formatted_response = f"@{sender_nick} \n\n{response_text}"
                
                # 将回答添加到数据库
                self.persistence_manager.add_message({
                    "message_id": str(uuid.uuid4()),
                    "thread_id": thread_id,
                    "role": "assistant",
                    "content": response_text,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "metadata": {
                        "reply_to": sender_staff_id,
                        "reply_to_nick": sender_nick,
                        "group_name": group_name,
                        "conversation_type": "群聊",
                        "robot_code": self.robot_code,
                        "conversation_id": conversation_id
                    }
                })
                
                # 发送回答到群聊（只在消息内容中@用户，不在标题中重复@）
                await self.sender.send_markdown_to_group(
                    conversation_id,
                    f"回复",  # 移除标题中的@
                    formatted_response
                )
                
        except Exception as e:
            logger.error(f"处理群聊消息时出错: {str(e)}", exc_info=True)
            # 发送错误消息
            await self.sender.send_markdown_to_group(
                conversation_id,
                "❌ 系统错误",
                f"抱歉 @{sender_nick}，处理您的请求时发生了系统错误。请稍后再试。"
            )

def main():
    """主函数"""
    logger.info("初始化BaseAgent...")
    agent = DingTalkAgent()
    
    try:
        agent.startup()  # 移除await关键字
    except KeyboardInterrupt:
        logger.info("收到终止信号，程序结束")
    except Exception as e:
        logger.error(f"程序运行时发生错误: {str(e)}", exc_info=True)
        
if __name__ == "__main__":
    # 在Windows下运行异步代码需要设置事件循环策略
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # 运行主程序
    main()  # 不再使用asyncio.run() 