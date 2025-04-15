import json

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from collections import deque
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from langchain_core.messages import AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from typing import Any
from uuid import UUID, uuid4

from src.model.agents.agents import DEFAULT_AGENT, PMHC_AFFINITY_PREDICTION, PATIENT_CASE_MRNA_AGENT,get_agent, initialize_agents
from src.model.agents.file_description import fileDescriptionAgent
from src.model.schema.schema import UserInput
from src.model.schema import MinioRequest,MinioResponse
from src.model.schema.models import OpenAIModelName
from src.utils.message_handling import (
    convert_message_content_to_string,
    langchain_to_chat_message,
    remove_tool_calls,
    _sse_response_example
)
from src.utils.log import logger

logger.info(f"========================start molly_langgraph backend==============================")
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化所有代理并获取连接对象
    connections = await initialize_agents()
    app.state.connections = connections  # 将连接对象存储在 app.state 中

    try:
        yield
    finally:
        # 关闭所有连接
        if hasattr(app.state, "connections"):
            for key, conn in app.state.connections.items():
                if conn:  # 确保连接对象存在
                    await conn.close()
                    logger.info(f"Closed connection: {key}")
app = FastAPI(lifespan=lifespan)

origins = [
    "*",  # 允许的来源，可以添加多个
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # 允许访问的源列表
    allow_credentials=True,  # 支持cookie跨域
    allow_methods=["*"],  # 允许的请求方法
    allow_headers=["*"],  # 允许的请求头
)

load_dotenv()

def _parse_input(user_input: UserInput) -> tuple[dict[str, Any], UUID]:
    run_id = uuid4()
    # thread_id = user_input.thread_id or str(uuid4())
    thread_id = user_input.conversation_id
    file_list = user_input.file_list

    # configurable = {"thread_id": thread_id, "model": user_input.model}
    configurable = {
                    "thread_id": thread_id, 
                    "model": OpenAIModelName.GPT_4O, 
                    "temperature":OpenAIModelName.TEMPERATURE, 
                    "max_tokens":OpenAIModelName.MAX_TOKENS,
                    "base_url":OpenAIModelName.BASE_URL,
                    "frequency_penalty":OpenAIModelName.FREQUENCY_PENALTY,
                    "file_list":file_list
                    
                    }
    # if user_input.agent_config:
    #     if overlap := configurable.keys() & user_input.agent_config.keys():
    #         raise HTTPException(
    #             status_code=422,
    #             detail=f"agent_config contains reserved keys: {overlap}",
    #         )
    #     configurable.update(user_input.agent_config)

    kwargs = {
        "input": {"messages": [HumanMessage(content=user_input.prompt)]},
        "config": RunnableConfig(
            configurable=configurable,
            run_id=run_id,
        ),
    }
    return kwargs, run_id

async def message_generator(
    user_input: UserInput, agent_id: str = DEFAULT_AGENT
) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent.

    This is the workhorse method for the /stream endpoint.
    """
    agent: CompiledStateGraph = get_agent(agent_id)
    kwargs, run_id = _parse_input(user_input)
    #上一次的yield类型
    previous_yield_type = "" 
    #定义队列
    tool_call_queue = deque()
    # Process streamed events from the graph and yield messages over the SSE stream.
    async for event in agent.astream_events(**kwargs, version="v2"):
        if not event:
            continue

        new_messages = []
        # Yield messages written to the graph state after node execution finishes.
        if (
            event["event"] == "on_chain_end"
            # on_chain_end gets called a bunch of times in a graph execution
            # This filters out everything except for "graph node finished"
            and any(t.startswith("graph:step:") for t in event.get("tags", []))
        ):
            if isinstance(event["data"]["output"], Command):
                new_messages = event["data"]["output"].update.get("messages", [])
            elif "messages" in event["data"]["output"]:
                new_messages = event["data"]["output"]["messages"]

        # Also yield intermediate messages from agents.utils.CustomData.adispatch().
        if event["event"] == "on_custom_event" and "custom_data_dispatch" in event.get("tags", []):
            new_messages = [event["data"]]
       
        for message in new_messages:
            try:
                chat_message = langchain_to_chat_message(message)
                chat_message.run_id = str(run_id)
            except Exception as e:
                logger.error(f"Error parsing message: {e}")
                yield f"data: {json.dumps({'type': 'error', 'content': 'Unexpected error'})}\n\n"
                continue

            # 过滤掉 LangGraph 重新发送的输入消息
            if chat_message.type == "human" and chat_message.content == user_input.prompt:
                continue

            # # 处理 tool 类型的消息
            # if chat_message.type == "tool":
            #     try:
            #         # 解析 content 字段中的字符串为字典
            #         content_dict = ast.literal_eval(chat_message.content)
            #         # 直接将字典赋值给 content，而不是转换为字符串
            #         chat_message.content = content_dict
            #     except (SyntaxError, ValueError, json.JSONDecodeError) as e:
            #         logger.error(f"解析 tool content 失败: {e}")
            #         chat_message.content = {"type": "error", "content": "Invalid tool content format"}
            # if chat_message.type == "tool":
            #     try:
            #         content_dict=json.loads(chat_message.content)
            #         chat_message.content = content_dict
            #     except (SyntaxError, ValueError, json.JSONDecodeError) as e:
            #         logger.error(f"解析 tool content 失败: {e}")
            #         chat_message.content = {"type": "error", "content": "Invalid tool content format"}
            # print(f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()}, ensure_ascii=False)}\n\n")
   
            if chat_message.type == "ai" and getattr(chat_message, "tool_calls", None) and previous_yield_type=="token":
                # 先 yield 一个换行符消息
                newline = "\n"
                previous_yield_type="token" 
                yield f"data: {json.dumps({'type': 'token', 'content': newline}, ensure_ascii=False)}\n\n"
            previous_yield_type="message"  

            #处理单轮，多个工具调用的前端渲染问题
            if chat_message.type == "ai" and getattr(chat_message, "tool_calls", None):
                # 处理工具调用
                if len(chat_message.tool_calls) > 1:
                    # 如果有多个工具调用，拆分成单独的消息存入队列
                    print(chat_message)
                    for tool_call in chat_message.tool_calls:
                        # 创建单个工具调用的消息副本
                        single_tool_message = chat_message.copy()
                        single_tool_message.tool_calls = [tool_call]
                        tool_call_queue.append(single_tool_message)
                    
                    # 不立即yield，等待tool消息时再处理
                    continue
                elif len(chat_message.tool_calls) == 1:
                    # 如果只有一个工具调用，直接存入队列
                    tool_call_queue.append(chat_message)
                    continue
            
            elif chat_message.type == "tool":
                # 当收到tool消息时，从队列中取出对应的调用消息
                if tool_call_queue:
                    queued_message = tool_call_queue.popleft()
                    # 先yield工具调用消息
                    yield f"data: {json.dumps({'type': 'message', 'content': queued_message.model_dump()}, ensure_ascii=False)}\n\n"
                    # 然后yield工具响应消息
                    yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()}, ensure_ascii=False)}\n\n"
            else:
            # 其他情况直接yield
                yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()}, ensure_ascii=False)}\n\n"
      

        # Yield tokens streamed from LLMs.
        if (
            event["event"] == "on_chat_model_stream"
            and user_input.stream_tokens
            and "llama_guard" not in event.get("tags", [])
        ):
            content = remove_tool_calls(event["data"]["chunk"].content)
            if content:
                # Empty content in the context of OpenAI usually means
                # that the model is asking for a tool to be invoked.
                # So we only print non-empty content.
                previous_yield_type="token" 

                yield f"data: {json.dumps({'type': 'token', 'content': convert_message_content_to_string(content)})}\n\n"
            continue
    previous_yield_type="DONE" 
    yield "data: [DONE]\n\n"



@app.post("/stream", response_class=StreamingResponse, responses=_sse_response_example())
async def chat(user_input: UserInput, agent_id: str = DEFAULT_AGENT) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """


    return StreamingResponse(
        message_generator(user_input, agent_id),
        media_type="text/event-stream",
    )

#pMHC_affinity_prediction的接口
@app.post("/demo_stream", response_class=StreamingResponse, responses=_sse_response_example())
async def chat(user_input: UserInput, agent_id: str = PMHC_AFFINITY_PREDICTION) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """


    return StreamingResponse(
        message_generator(user_input, agent_id),
        media_type="text/event-stream",
    )

#patient_case_mrna_stream的接口
@app.post("/patient_case_mrna_stream", response_class=StreamingResponse, responses=_sse_response_example())
async def chat(user_input: UserInput, agent_id: str = PATIENT_CASE_MRNA_AGENT) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """


    return StreamingResponse(
        message_generator(user_input, agent_id),
        media_type="text/event-stream",
    )

#对minio传来的文件进行描述
@app.post("/description", response_model=MinioResponse)
async def describe_text(request: MinioRequest):
    try:
        # 调用 LangChain 处理链
        result = fileDescriptionAgent.invoke({"file_name": request.file_name,"file_content":request.file_content})
        # 返回分析结果
        return MinioResponse(file_description=result.content)
    except Exception as e:
        # 捕获异常并返回错误信息
        raise HTTPException(status_code=500, detail=str(e))