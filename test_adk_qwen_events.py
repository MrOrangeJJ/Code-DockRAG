"""
测试Google ADK与阿里云Qwen模型的集成示例 - 使用Events跟踪版
使用LiteLLM适配器连接阿里云DashScope API，并通过Events记录详细过程
"""

from google.adk import Agent, Runner
from google.adk.tools.function_tool import FunctionTool
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
import google.genai.types as types
import os
import asyncio
import json
from dotenv import load_dotenv
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置
APP_NAME = "calculator_app"
USER_ID = "test_user"
SESSION_ID = "test_session"

# 加载环境变量
load_dotenv()
raw_model_name = os.getenv("MODEL", "qwen-plus")  # 从.env获取模型名称
model_name = f"dashscope/{raw_model_name}"  # 添加provider前缀

# 创建一个简单的计算工具
def calculate(a: float, b: float, operation: str) -> dict:
    """执行基本数学运算。
    
    根据提供的操作类型计算两个数字的结果。
    
    Args:
        a: 第一个数字
        b: 第二个数字
        operation: 要执行的操作（add、subtract、multiply、divide）
        
    Returns:
        dict: 包含计算结果的字典
    """
    logger.info(f"执行计算: {a} {operation} {b}")
    try:
        if operation == "add":
            return {"status": "success", "result": a + b}
        elif operation == "subtract":
            return {"status": "success", "result": a - b}
        elif operation == "multiply":
            return {"status": "success", "result": a * b}
        elif operation == "divide":
            if b == 0:
                return {"status": "error", "error_message": "除数不能为零"}
            return {"status": "success", "result": a / b}
        else:
            return {"status": "error", "error_message": f"不支持的操作: {operation}"}
    except Exception as e:
        return {"status": "error", "error_message": str(e)}

# 创建函数工具
calculate_tool = FunctionTool(func=calculate)

# 创建使用阿里云DashScope的Qwen Plus模型的代理
agent = Agent(
    model=LiteLlm(
        model="openai/qwen-plus",  # 添加openai/前缀以指示这是OpenAI兼容端点
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 使用OpenAI兼容模式
        api_key=os.getenv("DASHSCOPE_API_KEY", "sk-fb1aa03f23844b3f81c2f4163945094f"),  # API密钥
    ),
    name="qwen_calculator",
    instruction="你是一个有用的计算助手，能使用calculate工具执行数学运算。当用户提出计算请求时，请使用合适的工具帮助他们。请用中文回答问题。",
    tools=[calculate_tool]
)

# 创建会话服务
session_service = InMemorySessionService()

# 创建Runner
runner = Runner(
    app_name=APP_NAME,
    agent=agent,
    session_service=session_service
)

# 处理事件的辅助函数
def format_event_detail(event):
    """格式化事件详情为可读字符串"""
    details = []
    
    # 基本信息
    if hasattr(event, 'id'):
        details.append(f"ID: {event.id}")
    if hasattr(event, 'timestamp'):
        details.append(f"时间戳: {event.timestamp}")
    if hasattr(event, 'invocation_id'):
        details.append(f"调用ID: {event.invocation_id}")
    
    # 内容信息
    if hasattr(event, 'content') and event.content:
        if hasattr(event.content, 'parts') and event.content.parts:
            for i, part in enumerate(event.content.parts):
                if hasattr(part, 'text') and part.text:
                    details.append(f"文本内容: {part.text}")
                    
                # 检查函数调用
                if hasattr(part, 'function_call'):
                    func_call = part.function_call
                    if hasattr(func_call, 'name') and hasattr(func_call, 'args'):
                        details.append(f"工具调用: {func_call.name}")
                        details.append(f"参数: {json.dumps(func_call.args, ensure_ascii=False, indent=2)}")
                
                # 检查函数响应
                if hasattr(part, 'function_response'):
                    func_resp = part.function_response
                    if hasattr(func_resp, 'name') and hasattr(func_resp, 'response'):
                        details.append(f"工具响应: {func_resp.name}")
                        details.append(f"结果: {json.dumps(func_resp.response, ensure_ascii=False, indent=2)}")
    
    # 检查actions
    if hasattr(event, 'actions') and event.actions:
        if hasattr(event.actions, 'state_delta') and event.actions.state_delta:
            details.append(f"状态变更: {event.actions.state_delta}")
        if hasattr(event.actions, 'artifact_delta') and event.actions.artifact_delta:
            details.append(f"资源变更: {event.actions.artifact_delta}")
    
    return "\n".join(details)

# 测试代理的函数
async def main():
    logger.info("开始测试Qwen模型与Google ADK集成 - Events跟踪版...")
    
    try:
        # 确保会话存在
        session = session_service.create_session(
            user_id=USER_ID,
            session_id=SESSION_ID,
            app_name=APP_NAME
        )
        logger.info(f"创建会话: {session.id}")
        
        # 创建输入消息
        message_text = "计算5和7的和是多少？"
        logger.info(f"用户问题: {message_text}")
        
        # 构建输入消息内容
        text_part = types.Part(text=message_text)
        input_content = types.Content(
            parts=[text_part],
            role="user"
        )
        
        # 收集并详细记录每个事件
        print("\n=== 开始详细跟踪事件流 ===\n")
        events = runner.run_async(
            user_id=USER_ID,
            session_id=SESSION_ID,
            new_message=input_content
        )
        
        async for event in events:
            # 基本事件信息
            author = getattr(event, 'author', '未知来源')
            event_type = "最终响应" if (hasattr(event, 'is_final_response') and 
                                  callable(event.is_final_response) and 
                                  event.is_final_response()) else "中间事件"
            
            print(f"\n--- 事件 [{author}] ({event_type}) ---")
            
            # 检查是否有函数调用
            function_calls = event.get_function_calls() if hasattr(event, 'get_function_calls') and callable(event.get_function_calls) else []
            if function_calls:
                for i, call in enumerate(function_calls):
                    print(f"模型决定: 调用工具 {call.name}")
                    print(f"参数: {json.dumps(call.args, ensure_ascii=False, indent=2)}")
            
            # 检查是否有函数响应
            function_responses = event.get_function_responses() if hasattr(event, 'get_function_responses') and callable(event.get_function_responses) else []
            if function_responses:
                for i, resp in enumerate(function_responses):
                    print(f"工具执行结果: {resp.name}")
                    print(f"结果: {json.dumps(resp.response, ensure_ascii=False, indent=2)}")
            
            # 检查是否有文本内容
            if hasattr(event, 'content') and event.content and hasattr(event.content, 'parts'):
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        content_label = "思考过程:" if getattr(event, 'partial', False) else "输出内容:"
                        print(f"{content_label} {part.text}")
            
        
        print("\n测试完成!")
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

# 运行测试
if __name__ == "__main__":
    asyncio.run(main()) 