import aiohttp
import json
from typing import List, Dict, Any

from utils import logger
from utils.config import config

class LLMInterface:
    """封装与 LLM API 的交互逻辑"""

    def __init__(self):
        """初始化 LLM 接口"""
        # 未来可以考虑在这里管理 aiohttp.ClientSession
        pass

    def validate_message_roles(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """验证并修正消息中的角色，确保只使用LLM API支持的角色。

        Args:
            messages: 要验证的消息列表

        Returns:
            修正后的消息列表，只包含有效角色
        """
        valid_roles = {'system', 'assistant', 'user'}
        validated_messages = []

        for msg in messages:
            role = msg.get('role')
            content = msg.get('content', '')

            if role in valid_roles:
                # 角色有效，直接添加
                validated_messages.append(msg)
            elif role == 'tool_output':
                # 转换为assistant角色
                validated_messages.append({
                    "role": "assistant",
                    "content": f"[工具执行结果] {content}"
                })
            else:
                # 其他未知角色，默认转为user
                logger.warning(f"遇到未知角色 '{role}'，默认转换为 'user'")
                validated_messages.append({
                    "role": "user",
                    "content": content
                })

        return validated_messages

    async def call_llm_api(self, messages: List[Dict[str, str]], model_name: str = None, temperature: float = None, max_tokens: int = None, response_format: Dict = None, purpose: str = "未知目的") -> Dict[str, Any]:
        """
        调用配置的LLM API。
        Args:
            messages: 发送给LLM的消息列表。
            model_name: 可选，模型名称，默认使用配置的 MODEL。
            temperature: 可选，温度参数，默认使用配置的 TEMPERATURE。
            max_tokens: 可选，最大令牌数，默认使用配置的 MAX_TOKENS。
            response_format: 可选，响应格式，如 {"type": "json_object"}。
            purpose: 调用LLM的目的描述 (用于日志记录)。
        Returns:
            LLM的响应字典 (包含 role 和 content 或 error)。
        """
        # 在调用API前验证所有消息角色
        validated_messages = self.validate_message_roles(messages) # <-- Use the public method

        logger.info(f"LLM 调用 ({purpose}): 输入消息数 = {len(validated_messages)}")
        # 记录系统消息的长度而不是内容
        if validated_messages and validated_messages[0].get("role") == "system":
            system_len = len(validated_messages[0].get("content", ""))
            logger.debug(f"系统提示词长度: {system_len} 字符")

        headers = {
            "Authorization": f"Bearer {config.API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_name or config.MODEL,
            "messages": validated_messages,
            "max_tokens": max_tokens or config.MAX_TOKENS,
            "temperature": temperature or config.TEMPERATURE,
            "top_p": config.TOP_P,
        }

        # 添加响应格式（如果提供）
        if response_format:
            payload["response_format"] = response_format

        raw_response_text = "<未获取到响应文本>"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(config.API_ENDPOINT, headers=headers, json=payload) as response:
                    raw_response_text = await response.text() # 总是尝试获取原始文本
                    if response.status != 200:
                        logger.error(f"LLM API 错误: {response.status} - 原始响应: {raw_response_text}") # 记录原始响应
                        return {"role": "error", "content": f"LLM API调用失败: {response.status}"}

                    try:
                        result_data = await response.json(content_type=None) # 尝试解析JSON，忽略content-type
                    except json.JSONDecodeError as json_err:
                        logger.error(f"LLM API 响应 JSON 解析失败: {json_err}. 原始响应文本: {raw_response_text}")
                        return {"role": "error", "content": f"LLM响应JSON解析失败"}

                    if result_data and "choices" in result_data and result_data["choices"]:
                        choice = result_data["choices"][0]
                        llm_message = choice.get("message")
                        # 增加对 llm_message 内容是否存在的检查
                        if llm_message and llm_message.get("content") is not None: # 检查 content 是否存在且不为 None
                             logger.info(f"LLM API 响应成功.")
                             # 记录成功返回的content片段，便于追踪
                             logger.debug(f"LLM 返回内容片段: {str(llm_message.get('content'))[:100]}...")
                             return llm_message
                        else:
                             # content 为空或不存在
                             logger.warning(f"LLM API 响应成功，但 message 或 content 为空。Message: {llm_message}, 原始响应: {raw_response_text}")
                             return {"role": "error", "content": "LLM响应内容为空"} # 返回更具体的错误

                    # choices 为空或格式不正确
                    logger.warning(f"LLM API 响应格式不完整或无有效 choices。原始响应: {raw_response_text}")
                    return {"role": "error", "content": "LLM响应格式不完整"}

        except aiohttp.ClientError as e:
            logger.error(f"连接LLM API时出错: {e}")
            return {"role": "error", "content": f"连接LLM API失败: {e}"}
        except Exception as e:
            logger.error(f"调用LLM API时发生未知错误: {e}. 最后的原始响应文本 (可能不相关): {raw_response_text}", exc_info=True)
            return {"role": "error", "content": f"调用LLM时发生内部错误"} 