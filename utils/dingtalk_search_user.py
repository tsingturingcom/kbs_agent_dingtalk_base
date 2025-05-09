# -*- coding: utf-8 -*-
"""
钉钉用户ID查询工具

该工具使用钉钉开放平台API查询用户信息。
主要功能：
1. 根据姓名查询钉钉用户ID
2. 获取用户的详细信息（姓名、手机号、邮箱、部门、职位等）

使用方法：
python dingtalk_search_user.py

作者：Claude AI
日期：2025-04-22
"""

import sys
import os
import configparser

# 导入钉钉SDK相关模块
from alibabacloud_dingtalk.contact_1_0.client import Client as dingtalkcontact_1_0Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dingtalk.contact_1_0 import models as dingtalkcontact__1__0_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_util.client import Client as UtilClient


class DingTalkUserSearch:
    """钉钉用户搜索类，封装了用户查询相关的API调用"""
    
    def __init__(self):
        """初始化，从配置文件中读取钉钉应用凭证"""
        # 获取项目根目录的config.ini路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(current_dir)
        config_path = os.path.join(root_dir, 'config.ini')
        
        # 读取配置文件
        config = configparser.ConfigParser()
        # 设置为不区分大小写
        config.optionxform = str
        config.read(config_path, encoding='utf-8')
        
        # 获取配置信息 - 支持不区分大小写
        dingtalk_section = None
        for section in config.sections():
            if section.lower() == 'dingtalk_config':
                dingtalk_section = section
                break
        
        if not dingtalk_section:
            raise KeyError("配置文件中缺少dingtalk_config部分")
            
        # 获取配置项，不区分大小写
        def get_config(section, key):
            for k in config[section]:
                if k.lower() == key.lower():
                    return config[section][k]
            raise KeyError(f"配置项 {key} 不存在")
        
        self.client_id = get_config(dingtalk_section, 'DINGTALK_CLIENT_ID')
        self.client_secret = get_config(dingtalk_section, 'DINGTALK_CLIENT_SECRET')
        self.api_endpoint_auth = get_config(dingtalk_section, 'API_ENDPOINT_AUTH')
        
    def create_client(self) -> dingtalkcontact_1_0Client:
        """
        初始化钉钉API客户端
        @return: 钉钉通讯录API客户端实例
        """
        # 配置钉钉OpenAPI客户端
        config = open_api_models.Config()
        config.protocol = 'https'        # 使用HTTPS协议
        config.region_id = 'central'     # 区域设置为central
        
        # 返回通讯录API客户端实例
        return dingtalkcontact_1_0Client(config)
    
    def get_access_token(self):
        """
        获取钉钉访问令牌
        @return: 访问令牌字符串
        @raises: Exception 如果获取令牌失败
        """
        import requests
        
        # 构建获取access_token的URL和参数
        url = f"{self.api_endpoint_auth}/gettoken"
        params = {
            'appkey': self.client_id,
            'appsecret': self.client_secret
        }
        
        # 发送GET请求
        response = requests.get(url, params=params)
        result = response.json()
        
        # 检查响应是否成功
        if result.get('errcode') == 0:
            return result.get('access_token')
        else:
            raise Exception(f"获取access_token失败: {result.get('errmsg')}")
    
    def get_user_detail(self, userid):
        """
        获取用户详细信息
        @param userid: 用户ID
        @return: 用户详细信息字典，获取失败则返回None
        """
        try:
            import requests
            
            # 获取访问令牌
            access_token = self.get_access_token()
            
            # 构建获取用户详情的API请求
            url = f"{self.api_endpoint_auth}/topapi/v2/user/get"
            headers = {
                'Content-Type': 'application/json'
            }
            data = {
                'userid': userid  # 需要查询的用户ID
            }
            
            # 发送POST请求
            response = requests.post(
                url, 
                params={'access_token': access_token},  # 通过URL参数传递access_token
                json=data                              # 请求体使用JSON格式
            )
            
            # 解析响应
            result = response.json()
            
            # 检查响应是否成功
            if result.get('errcode') == 0 and 'result' in result:
                return result.get('result')
            else:
                print(f"获取用户详情失败: {result.get('errmsg', '未知错误')}")
                return None
        except Exception as e:
            print(f"获取用户详情异常: {str(e)}")
            return None

    def search_user(self, name, offset=0, size=20, full_match=None):
        """
        根据姓名查询用户ID
        @param name: 查询关键词（姓名）
        @param offset: 分页起始位置
        @param size: 分页大小
        @param full_match: 是否全匹配，设为None表示不使用此参数
        @return: 查询结果列表，失败返回空列表
        
        注意：函数中包含用于调试的API响应打印语句（已注释），
        如需调试API响应内容，可取消注释 print(f"API响应: {response}") 语句
        """
        # 创建钉钉API客户端
        client = self.create_client()
        
        # 获取访问令牌
        access_token = self.get_access_token()
        
        # 设置请求头，主要是包含访问令牌
        search_user_headers = dingtalkcontact__1__0_models.SearchUserHeaders()
        search_user_headers.x_acs_dingtalk_access_token = access_token
        
        # 设置查询参数：查询关键词、分页起始位置、分页大小
        search_user_request = dingtalkcontact__1__0_models.SearchUserRequest(
            query_word=name,  # 搜索关键词
            offset=offset,    # 分页起始位置
            size=size         # 分页大小
        )
        
        # 只有当full_match不为None时才设置全匹配参数
        if full_match is not None:
            search_user_request.full_match_field = full_match
        
        try:
            # 发送用户搜索请求
            # 这里使用了SDK提供的search_user_with_options方法
            # 该方法封装了对钉钉API的调用：/v1.0/contact/users/search
            response = client.search_user_with_options(
                search_user_request,      # 请求参数
                search_user_headers,      # 请求头
                util_models.RuntimeOptions()  # 运行时选项
            )
            
            # 打印完整的API响应内容（用于调试，正式环境可注释掉）
            # 这行代码可以显示API的原始返回结果，包括：
            # - headers: HTTP响应头信息
            # - statusCode: HTTP状态码，200表示成功
            # - body: 响应主体，包含查询结果
            #   - hasMore: 是否有更多结果
            #   - list: 匹配的用户ID列表
            #   - totalCount: 匹配的用户总数
            print(f"API响应: {response}")  # 取消注释以查看完整API响应
            
            # 处理并返回查询结果
            if hasattr(response.body, 'list') and response.body.list:
                # 获取匹配的用户ID列表
                user_ids = response.body.list
                print(f"找到用户ID: {user_ids}")
                
                # 获取每个用户的详细信息
                users_info = []
                for user_id in user_ids:
                    # 调用获取用户详情的API
                    user_detail = self.get_user_detail(user_id)
                    if user_detail:
                        # 如果成功获取到详情，加入结果列表
                        users_info.append(user_detail)
                    else:
                        # 如果获取详情失败，则只返回ID和搜索的姓名
                        users_info.append({"userid": user_id, "name": name})
                
                return users_info
            else:
                # 未找到匹配用户，返回空列表
                return []
        except Exception as err:
            # 处理异常情况
            if hasattr(err, 'code') and hasattr(err, 'message'):
                print(f"查询失败: {err.message}")
            else:
                print(f"查询失败: {str(err)}")
            return []


def main():
    """主函数，处理用户输入并显示查询结果"""
    # 创建搜索实例
    searcher = DingTalkUserSearch()
    
    # 用户输入姓名
    name = input("请输入要查询的用户姓名: ")
    
    print(f"正在查询用户 '{name}' 的信息...")
    # 调用搜索方法
    users = searcher.search_user(name)
    
    # 显示查询结果
    if users:
        print(f"\n查询到 {len(users)} 个匹配用户:")
        for i, user in enumerate(users, 1):
            print(f"\n用户 {i}:")
            print(f"用户ID: {user.get('userid')}")
            print(f"姓名: {user.get('name', '未知')}")
            
            # 打印其他可能存在的用户信息
            if user.get('mobile'):
                print(f"手机号: {user.get('mobile')}")
            if user.get('email'):
                print(f"邮箱: {user.get('email')}")
            if user.get('department'):
                print(f"部门ID: {user.get('department')}")
            if user.get('title'):
                print(f"职位: {user.get('title')}")
    else:
        print(f"未找到匹配用户 '{name}'")


# 程序入口
if __name__ == "__main__":
    main() 