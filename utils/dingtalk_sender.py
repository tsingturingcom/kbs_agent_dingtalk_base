import os
import json
import time
import asyncio
import logging
from typing import List, Optional

import aiohttp
from utils.config import config # 从baseagent的utils导入配置
from utils import logger # 使用baseagent的logger

class DingTalkSender:
    """
    异步发送钉钉机器人消息的类。
    
    负责管理 access_token 的获取与刷新，并提供发送文本和 Markdown 消息
    到单聊和群聊的异步方法。
    """
    def __init__(self):
        """初始化 DingTalkSender"""
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._lock = asyncio.Lock() # 用于令牌刷新的异步锁
        
        # 从配置加载钉钉相关设置
        try:
            self.client_id = config.config.get('dingtalk_config', 'dingtalk_client_id')
            self.client_secret = config.config.get('dingtalk_config', 'dingtalk_client_secret')
            self.robot_code = config.config.get('dingtalk_config', 'dingtalk_robot_code')
            
            # 检查可选配置项
            if config.config.has_option('dingtalk_config', 'api_endpoint_auth'):
                self.api_endpoint_auth = config.config.get('dingtalk_config', 'api_endpoint_auth')
            else:
                self.api_endpoint_auth = 'https://oapi.dingtalk.com'
                
            if config.config.has_option('dingtalk_config', 'api_endpoint_contact'):
                self.api_endpoint_contact = config.config.get('dingtalk_config', 'api_endpoint_contact')
            else:
                self.api_endpoint_contact = 'https://api.dingtalk.com'
        except Exception as e:
            logger.error(f"初始化DingTalkSender时加载配置错误: {e}")
            raise

    async def _refresh_token(self) -> bool:
        """
        异步刷新钉钉访问令牌。
        
        Returns:
            bool: True 表示成功获取或刷新令牌，False 表示失败。
        """
        logger.info("尝试刷新钉钉 Access Token...")
        url = f"{self.api_endpoint_auth}/gettoken"
        params = {
            'appkey': self.client_id,
            'appsecret': self.client_secret
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"获取 Access Token 请求失败，状态码: {response.status}, 响应: {await response.text()}")
                        return False
                        
                    result = await response.json()
                    
                    if result.get('errcode') == 0:
                        self._access_token = result.get('access_token')
                        # 提前 5 分钟过期
                        expires_in = result.get('expires_in', 7200)
                        self._token_expires_at = time.time() + expires_in - 300 
                        logger.info(f"成功刷新钉钉 Access Token，有效期至: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._token_expires_at))}")
                        return True
                    else:
                        logger.error(f"获取 Access Token 失败: {result}")
                        self._access_token = None
                        self._token_expires_at = 0
                        return False
        except aiohttp.ClientError as e:
            logger.error(f"请求 Access Token 时发生网络错误: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"刷新 Access Token 时发生未知错误: {e}", exc_info=True)
            return False

    async def ensure_token(self) -> Optional[str]:
        """
        确保 access_token 有效，如果无效或即将过期则刷新。
        使用异步锁防止并发刷新。
        
        Returns:
            Optional[str]: 有效的 access_token，如果获取失败则返回 None。
        """
        async with self._lock:
            # 再次检查，因为可能在等待锁的时候其他协程已经刷新了
            if self._access_token and time.time() < self._token_expires_at:
                return self._access_token
            
            if await self._refresh_token():
                return self._access_token
            else:
                return None

    async def _send_request(self, url: str, data: dict) -> bool:
        """
        内部方法，用于发送 POST 请求到钉钉 API。
        包含重试机制处理临时网络问题。
        
        Args:
            url (str): 目标 API URL。
            data (dict): 请求体数据。
            
        Returns:
            bool: True 表示发送成功 (API 返回 processQueryKey)，False 表示失败。
        """
        token = await self.ensure_token()
        if not token:
            logger.error("无法获取有效的 Access Token，发送请求中止。")
            return False
            
        headers = {
            'Content-Type': 'application/json',
            'x-acs-dingtalk-access-token': token
        }
        
        # 定义重试参数
        max_retries = 3
        retry_count = 0
        retry_delay = 1.0  # 初始延迟1秒
        
        while retry_count < max_retries:
            try:
                async with aiohttp.ClientSession() as session:
                    logger.debug(f"发送钉钉 API 请求: URL={url}, Headers={headers}, Body={json.dumps(data, ensure_ascii=False)}")
                    async with session.post(url, headers=headers, json=data) as response:
                        response_text = await response.text()
                        logger.debug(f"钉钉 API 响应: Status={response.status}, Body={response_text}")
                        
                        if response.status != 200:
                            logger.error(f"钉钉 API 请求失败，状态码: {response.status}, 响应: {response_text}")
                            return False
                            
                        result = json.loads(response_text) # 尝试解析 JSON
                        
                        # 检查 v1.0 API 的成功标志 (通常是 processQueryKey)
                        if result.get('processQueryKey') or (isinstance(result, dict) and result.get('success', False)) or (isinstance(result, dict) and result.get('errcode') == 0): # 兼容不同接口
                            logger.info(f"钉钉消息发送成功。 API: {url.split('/')[-1]}")
                            return True
                        else:
                            # 记录详细错误，包括可能的 errcode 和 errmsg
                            errcode = result.get('errcode', 'N/A')
                            errmsg = result.get('errmsg', result.get('message', '无详细错误信息'))
                            logger.error(f"钉钉消息发送失败: 返回码={errcode}, 消息='{errmsg}', 完整响应={result}")
                            return False
                            
            except aiohttp.ClientConnectorError as e:
                # 网络连接错误，可能是临时DNS问题
                retry_count += 1
                if retry_count < max_retries:
                    logger.warning(f"钉钉 API 网络连接错误 (尝试 {retry_count}/{max_retries}): {e}, 将在 {retry_delay}秒后重试")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    logger.error(f"钉钉 API 网络连接错误，已达到最大重试次数: {e}", exc_info=True)
                    return False
            except aiohttp.ClientError as e:
                # 其他客户端错误
                retry_count += 1
                if retry_count < max_retries:
                    logger.warning(f"钉钉 API 网络错误 (尝试 {retry_count}/{max_retries}): {e}, 将在 {retry_delay}秒后重试")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    logger.error(f"发送钉钉消息时发生网络错误，已达到最大重试次数: {e}", exc_info=True)
                    return False
            except json.JSONDecodeError as e:
                logger.error(f"解析钉钉 API 响应 JSON 时失败: {e}, 响应文本: '{response_text}'", exc_info=True)
                return False
            except Exception as e:
                logger.error(f"发送钉钉消息时发生未知错误: {e}", exc_info=True)
                return False
        
        return False  # 所有重试都失败

    async def send_text_to_user(self, user_id: str, content: str) -> bool:
        """
        异步发送文本消息给单个用户。
        
        Args:
            user_id (str): 用户的 StaffID 或 UserID。
            content (str): 消息内容。
            
        Returns:
            bool: True 表示成功，False 表示失败。
        """
        url = f"{self.api_endpoint_contact}/v1.0/robot/oToMessages/batchSend"
        data = {
            "robotCode": self.robot_code,
            "userIds": [user_id],
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": content}, ensure_ascii=False)
        }
        return await self._send_request(url, data)

    async def send_markdown_to_user(self, user_id: str, title: str, text: str) -> bool:
        """
        异步发送 Markdown 消息给单个用户。
        
        Args:
            user_id (str): 用户的 StaffID 或 UserID。
            title (str): Markdown 消息的标题。
            text (str): Markdown 格式的消息内容。
            
        Returns:
            bool: True 表示成功，False 表示失败。
        """
        url = f"{self.api_endpoint_contact}/v1.0/robot/oToMessages/batchSend"
        data = {
            "robotCode": self.robot_code,
            "userIds": [user_id],
            "msgKey": "sampleMarkdown",
            "msgParam": json.dumps({
                "title": title,
                "text": text
            }, ensure_ascii=False)
        }
        return await self._send_request(url, data)

    async def send_text_to_group(self, conversation_id: str, content: str) -> bool:
        """
        异步发送文本消息到群聊。
        
        Args:
            conversation_id (str): 群聊的 openConversationId。
            content (str): 消息内容。
            
        Returns:
            bool: True 表示成功，False 表示失败。
        """
        url = f"{self.api_endpoint_contact}/v1.0/robot/groupMessages/send"
        data = {
            "robotCode": self.robot_code,
            "openConversationId": conversation_id,
            "msgKey": "sampleText",
            "msgParam": json.dumps({"content": content}, ensure_ascii=False)
        }
        return await self._send_request(url, data)

    async def send_markdown_to_group(self, conversation_id: str, title: str, text: str) -> bool:
        """
        异步发送 Markdown 消息到群聊。
        
        Args:
            conversation_id (str): 群聊的 openConversationId。
            title (str): Markdown 消息的标题。
            text (str): Markdown 格式的消息内容。
            
        Returns:
            bool: True 表示成功，False 表示失败。
        """
        url = f"{self.api_endpoint_contact}/v1.0/robot/groupMessages/send"
        data = {
            "robotCode": self.robot_code,
            "openConversationId": conversation_id,
            "msgKey": "sampleMarkdown",
            "msgParam": json.dumps({
                "title": title,
                "text": text
            }, ensure_ascii=False)
        }
        return await self._send_request(url, data) 