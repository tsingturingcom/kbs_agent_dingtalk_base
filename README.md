# kbs_agent_dingtalk_base 钉钉智能对话助手

kbs_agent_dingtalk_base是一个基于大语言模型的钉钉聊天机器人框架，支持单聊和群聊，具有对话记忆和上下文管理功能。该项目专为中文应用场景设计，可以连接到钉钉平台并与各种大语言模型API集成。

## 功能特点

- **钉钉集成**：完整支持钉钉单聊和群聊消息处理
- **对话记忆**：持久化存储所有对话历史，支持长期记忆
- **上下文管理**：智能管理对话上下文，自动处理token限制
- **数据库支持**：支持SQLite本地存储和Supabase云端存储
- **多模型支持**：可配置连接不同的大语言模型API
- **线程安全**：支持多线程并发处理消息
- **可扩展架构**：模块化设计，易于扩展和定制

## 系统架构

系统由以下主要组件构成：

### 核心组件

- **DingTalkAgent**：主要入口类，处理钉钉消息并调用其他组件
- **ContextManager**：管理对话上下文，处理token计数和上下文优化
- **PersistenceManager**：负责数据持久化，管理线程和消息的存储和检索
- **LLMInterface**：与大语言模型API交互的接口封装

### 辅助组件

- **DingTalkSender**：发送消息回钉钉的工具类
- **配置管理**：通过config.ini管理所有系统配置
- **日志系统**：详细的日志记录功能

## 文件功能说明

### 主要文件详解

- **dingtalk_agent.py**: 系统入口文件，实现钉钉机器人的核心逻辑，包括消息接收、处理和回复
- **config.ini**: 配置文件，包含钉钉、LLM和数据库等各项配置

### utils目录

- **config.py**: 配置加载和管理模块，负责解析config.ini并提供配置接口
- **logger.py**: 日志系统，提供全局一致的日志记录功能
- **dingtalk_sender.py**: 钉钉消息发送模块，封装各种钉钉消息发送功能
- **docker-compose.yml**: Docker配置文件，用于Supabase开发环境的搭建

### agent/core目录

- **llm_interface.py**: LLM接口模块，负责与大语言模型API的通信和处理
- **context_manager.py**: 上下文管理模块，处理对话历史记忆、token计数和上下文优化
- **persistence_manager.py**: 数据持久化基类，负责SQLite数据库的操作
- **supabase_persistence_manager.py**: Supabase数据库持久化实现
- **persistence_factory.py**: 工厂类，根据配置创建适当的持久化管理器
- **prompts.py**: 系统提示词管理，处理提示词模板和动态生成提示词

## 安装和配置

### 环境要求

- Python 3.8+
- SQLite3（默认）或Supabase（可选）

### 安装步骤

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 配置`config.ini`：
   - 填入您的钉钉机器人配置（client_id, client_secret等）
   - 配置大语言模型API接入参数
   - 设置数据库配置（默认使用SQLite）

### 钉钉配置

您需要在钉钉开发者平台创建应用并获取以下信息：
- 机器人的ClientID和ClientSecret
- 机器人的RobotCode和AgentID
- 配置回调URL和订阅相应的事件

## 使用方法

### 启动机器人

```bash
python dingtalk_agent.py
```

启动后，机器人将自动连接钉钉平台，开始监听和响应消息。

### 自定义系统提示词

可以通过修改`agent/core/prompts.py`文件来自定义系统提示词和模板。

### 数据库选择

系统默认使用SQLite本地数据库，存储在`baseagent.db`文件中。如需使用Supabase云数据库，请修改config.ini中的database_type设置并填写Supabase配置。

## 数据模型

系统使用两个主要表存储数据：

1. **threads表**：存储对话线程信息
   - thread_id：线程唯一标识，根据会话类型不同有不同的生成规则
   - robot_code：机器人编码
   - conversation_type：会话类型（单聊/群聊）
   - 其他会话元数据

2. **messages表**：存储所有消息
   - message_id：消息唯一标识
   - thread_id：所属线程
   - role：消息角色（user/assistant）
   - content：消息内容
   - 其他消息元数据

### thread_id命名规则

系统根据不同会话类型使用不同的thread_id生成规则：

- **单聊场景**: `{robot_code}_{user_id}`
  - 例如：`ding7qothi6xsgezy1h6_user12345`
  - 这确保每个用户与机器人的对话都有唯一标识

- **群聊场景**: 直接使用钉钉提供的`conversation_id`
  - 这确保群聊中的所有消息都关联到同一个会话线程

thread_id是系统的核心标识，用于关联对话历史、检索消息记录和管理上下文。

## 高级特性

### 上下文优化

系统会根据模型的最大token限制自动优化对话历史，确保不超出限制并保留最重要的上下文信息。

### 并发处理

系统支持并发处理多个用户的消息，使用线程安全的数据库连接管理。

## 技术栈

- Python 3.8+
- 数据库：SQLite3 / Supabase
- 大语言模型：通过API接入各种模型
- 钉钉API：通过dingtalk-stream SDK接入

## 项目结构

```
baseagent/
├── agent/               # 核心代理组件
│   └── core/            # 核心功能模块
│       ├── context_manager.py    # 上下文管理
│       ├── llm_interface.py      # LLM接口
│       ├── persistence_manager.py # 持久化管理
│       ├── prompts.py            # 系统提示词
│       └── ...
├── utils/               # 工具函数和辅助类
│   ├── config.py        # 配置管理
│   ├── dingtalk_sender.py # 钉钉消息发送
│   └── logger.py        # 日志工具
├── logs/                # 日志文件夹
├── baseagent.db         # SQLite数据库
├── config.ini           # 配置文件
├── requirements.txt     # 依赖声明
└── dingtalk_agent.py    # 主程序入口
```

## 常见问题排查

如遇到问题，请先检查：
1. 钉钉配置是否正确
2. LLM API连接是否正常
3. 查看logs目录下的日志文件获取详细错误信息

## 许可证

本项目使用 [Apache License 2.0](LICENSE) 开源许可证。

```
Copyright 2024 tsingturingcom

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

## 贡献指南

欢迎提交Issue和Pull Request贡献代码。

## 联系方式

[联系方式信息]
