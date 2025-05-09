"""
存储系统提示词和相关提示模板
"""
import datetime
import json

# 默认系统提示词
DEFAULT_SYSTEM_PROMPT = """你是一个智能助手，使用中文与用户对话。
你的回答应当简洁、准确、有帮助。
如果你不知道某个问题的答案，请直接说你不知道，不要编造信息。
在回答问题时，请确保提供有用、相关的信息，并保持友好和专业的语气。
"""

# 可以添加其他提示词模板
PROMPT_TEMPLATES = {
    "简洁": {
        "role": "system",
        "content": "你是一个智能助手。简明扼要回答用户的问题，避免冗长解释。"
    },
    "专业": {
        "role": "system",
        "content": "你是一个专业领域的助手。提供准确、深入的回答，包含相关专业术语和解释。"
    },
    "友好": {
        "role": "system",
        "content": "你是一个友好的对话助手。使用轻松愉快的语气交流，像朋友一样回答问题。"
    }
}

def get_system_prompt(prompt_type=None, context_info=None):
    """
    获取系统提示词，并注入上下文信息
    
    Args:
        prompt_type: 提示词类型，如果为None则返回默认提示词
        context_info: 上下文信息字典，包含用户信息、聊天类型等
        
    Returns:
        包含角色和内容的提示词字典
    """
    # 获取基础提示词
    if prompt_type and prompt_type in PROMPT_TEMPLATES:
        prompt = PROMPT_TEMPLATES[prompt_type].copy()
    else:
        prompt = {
            "role": "system",
            "content": DEFAULT_SYSTEM_PROMPT
        }
    
    # 如果有上下文信息，注入到提示词中
    if context_info:
        # 格式化当前时间
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conversation_type = context_info.get('conversation_type', '单聊')
        
        # 构建基本上下文信息文本
        context_text = f"""
--- 会话信息 ---
当前时间: {current_time}
用户ID: {context_info.get('user_id', '未知')}
用户昵称: {context_info.get('user_nick', '未知')}
会话类型: {conversation_type}
机器人ID: {context_info.get('robot_code', '未知')}
"""
        
        # 根据会话类型添加不同的场景信息
        if conversation_type == '群聊':
            context_text += f"""
群聊ID: {context_info.get('conversation_id', '未知')}
群聊名称: {context_info.get('group_name', '未知群聊')}

--- 场景提示 ---
这是一个开放的群聊场景。请注意：
1. 这个群里可能有多个用户和多个机器人同时交流
2. 你的回复对群里所有人可见，不是私密的
3. 你应该主动@提及你要回复的用户，保持对话清晰
4. 了解群聊上下文，参与群内讨论
5. 群名称可能会变化，但群ID保持不变
"""
        else:  # 单聊场景
            context_text += f"""
--- 场景提示 ---
这是一个私密的一对一聊天场景。请注意：
1. 这是你与用户之间的私密对话，只有你们两人可见
2. 你可以提供个性化、私人的帮助和建议
3. 用户可能期待更直接、更私人化的回应
4. 注重保护用户隐私，不要泄露或询问敏感信息
5. 建立信任感和持续的一对一关系
"""
        
        # 添加附加信息（如果有）
        if context_info.get('additional_info'):
            context_text += f"""
附加信息: {json.dumps(context_info.get('additional_info'), ensure_ascii=False)}
"""
        
        # 将上下文信息添加到提示词
        prompt['content'] = context_text + "\n" + prompt['content']
    
    return prompt 