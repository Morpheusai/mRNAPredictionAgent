import inspect
import json

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Interrupt
from langgraph.pregel import Pregel
from typing import Any, Union
from uuid import UUID, uuid4

from src.agents.agents import (
    DEFAULT_AGENT, 
    PMHC_AFFINITY_PREDICTION, 
    PATIENT_CASE_MRNA_AGENT,
    NEO_ANTIGEN,
    PREDICT_NEO_ANTIGEN,
    QA_PREDICT_NEO,
    get_all_agent_info,
    get_all_agents,
    get_agent
)
from src.agents.files.file_description import fileDescriptionAgent
from src.agents.files.patient_info_formatter import PatientInfoDescriptionAgent
from src.agents.tools.parameters import ToolParameters

from src.memory import initialize_store, initialize_database
from src.schema.schema import (
    UserInput, 
    MinioRequest, 
    MinioResponse, 
    PatientInfoRequest, 
    PatientInfoResponse,
    PredictUserInput
)
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
    """
    Configurable lifespan that initializes the appropriate database checkpointer and store
    based on settings.
    """
    try:
        # Initialize both checkpointer (for short-term memory) and store (for long-term memory)
        async with initialize_database() as saver, initialize_store() as store:
            # Set up both components
            if hasattr(saver, "setup"):  # ignore: union-attr
                await saver.setup()
            # Only setup store for Postgres as InMemoryStore doesn't need setup
            if hasattr(store, "setup"):  # ignore: union-attr
                await store.setup()

            # Configure agents with both memory components
            agents = get_all_agent_info()
            for a in agents:
                agent = get_agent(a.key)
                # Set checkpointer for thread-scoped memory (conversation history)
                agent.checkpointer = saver
                # Set store for long-term memory (cross-conversation knowledge)
                agent.store = store
            yield
    except Exception as e:
        logger.error(f"Error during database/store initialization: {e}")
        raise

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

def _parse_input(user_input: Union[UserInput, PredictUserInput]) -> tuple[dict[str, Any], UUID]:
    run_id = uuid4()
    thread_id = user_input.conversation_id
    
    # 基础配置
    configurable = {
        "thread_id": thread_id, 
    }
    
    # 根据输入类型添加特定配置
    if isinstance(user_input, UserInput):
        configurable["file_list"] = user_input.file_list
    elif isinstance(user_input, PredictUserInput):
        configurable.update(
            {
                "file_path": user_input.file_path,
                "mhc_allele": user_input.mhc_allele,
                "cdr3": user_input.cdr3,
                "patient_id": user_input.patient_id,
                "predict_id": user_input.predict_id,
                "conversation_id" : user_input.conversation_id,
            }
        )
        # if user_input.parameters:
        tool_parameters = ToolParameters(**user_input.parameters)
        configurable.update(
            {
                "tool_parameters": tool_parameters,
            }
        )

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

# async def message_generator(
#     user_input: UserInput, agent_id: str = DEFAULT_AGENT
# ) -> AsyncGenerator[str, None]:
#     """
#     Generate a stream of messages from the agent.

#     This is the workhorse method for the /stream endpoint.
#     """
#     agent: CompiledStateGraph = get_agent(agent_id)
#     kwargs, run_id = _parse_input(user_input)
#     #上一次的yield类型
#     previous_yield_type = "" 
#     #定义队列
#     tool_call_queue = deque()
#     # Process streamed events from the graph and yield messages over the SSE stream.
#     async for event in agent.astream_events(**kwargs, version="v2",stream_mode="custom"):
#         if not event:
#             continue
#         print("2222222222222222")
#         print(event)
#         new_messages = []
#         # Yield messages written to the graph state after node execution finishes.
#         if (
#             event["event"] == "on_chain_end"
#             # on_chain_end gets called a bunch of times in a graph execution
#             # This filters out everything except for "graph node finished"
#             and any(t.startswith("graph:step:") for t in event.get("tags", []))
#         ):
#             if isinstance(event["data"]["output"], Command):
#                 new_messages = event["data"]["output"].update.get("messages", [])
#             elif "messages" in event["data"]["output"]:
#                 new_messages = event["data"]["output"]["messages"]

#         # Also yield intermediate messages from agents.utils.CustomData.adispatch().
#         if event["event"] == "on_custom_event" and "custom_data_dispatch" in event.get("tags", []):
#             new_messages = [event["data"]]
       
#         for message in new_messages:
#             try:
#                 chat_message = langchain_to_chat_message(message)
#                 chat_message.run_id = str(run_id)
#             except Exception as e:
#                 logger.error(f"Error parsing message: {e}")
#                 yield f"data: {json.dumps({'type': 'error', 'content': 'Unexpected error'})}\n\n"
#                 continue

#             # 过滤掉 LangGraph 重新发送的输入消息
#             if chat_message.type == "human" and chat_message.content == user_input.prompt:
#                 continue

#             # # 处理 tool 类型的消息
#             # if chat_message.type == "tool":
#             #     try:
#             #         # 解析 content 字段中的字符串为字典
#             #         content_dict = ast.literal_eval(chat_message.content)
#             #         # 直接将字典赋值给 content，而不是转换为字符串
#             #         chat_message.content = content_dict
#             #     except (SyntaxError, ValueError, json.JSONDecodeError) as e:
#             #         logger.error(f"解析 tool content 失败: {e}")
#             #         chat_message.content = {"type": "error", "content": "Invalid tool content format"}
#             # if chat_message.type == "tool":
#             #     try:
#             #         content_dict=json.loads(chat_message.content)
#             #         chat_message.content = content_dict
#             #     except (SyntaxError, ValueError, json.JSONDecodeError) as e:
#             #         logger.error(f"解析 tool content 失败: {e}")
#             #         chat_message.content = {"type": "error", "content": "Invalid tool content format"}
#             # print(f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()}, ensure_ascii=False)}\n\n")
   
#             if chat_message.type == "ai" and getattr(chat_message, "tool_calls", None) and previous_yield_type=="token":
#                 # 先 yield 一个换行符消息
#                 newline = "\n"
#                 previous_yield_type="token" 
#                 yield f"data: {json.dumps({'type': 'token', 'content': newline}, ensure_ascii=False)}\n\n"
#             previous_yield_type="message"  

#             #处理单轮，多个工具调用的前端渲染问题
#             if chat_message.type == "ai" and getattr(chat_message, "tool_calls", None):
#                 # 处理工具调用
#                 if len(chat_message.tool_calls) > 1:
#                     # 如果有多个工具调用，拆分成单独的消息存入队列
#                     print(chat_message)
#                     for tool_call in chat_message.tool_calls:
#                         # 创建单个工具调用的消息副本
#                         single_tool_message = chat_message.copy()
#                         single_tool_message.tool_calls = [tool_call]
#                         tool_call_queue.append(single_tool_message)
                    
#                     # 不立即yield，等待tool消息时再处理
#                     continue
#                 elif len(chat_message.tool_calls) == 1:
#                     # 如果只有一个工具调用，直接存入队列
#                     tool_call_queue.append(chat_message)
#                     continue
            
#             elif chat_message.type == "tool":
#                 # 当收到tool消息时，从队列中取出对应的调用消息
#                 if tool_call_queue:
#                     queued_message = tool_call_queue.popleft()
#                     # 先yield工具调用消息
#                     yield f"data: {json.dumps({'type': 'message', 'content': queued_message.model_dump()}, ensure_ascii=False)}\n\n"
#                     # 然后yield工具响应消息
#                     yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()}, ensure_ascii=False)}\n\n"
#             else:
#             # 其他情况直接yield
#                 yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()}, ensure_ascii=False)}\n\n"
      

#         # Yield tokens streamed from LLMs.
#         if (
#             event["event"] == "on_chat_model_stream"
#             and user_input.stream_tokens
#             and "llama_guard" not in event.get("tags", [])
#         ):
#             content = remove_tool_calls(event["data"]["chunk"].content)
#             if content:
#                 # Empty content in the context of OpenAI usually means
#                 # that the model is asking for a tool to be invoked.
#                 # So we only print non-empty content.
#                 previous_yield_type="token" 

#                 yield f"data: {json.dumps({'type': 'token', 'content': convert_message_content_to_string(content)})}\n\n"
#             continue
#         #捕获工具内的响应
#         if (
#             event.get("event") == "on_chain_stream"
#             and event.get("name") == "LangGraph"
#             and "chunk" in event.get("data", {})
#         ):
#             chunk_content = event["data"]["chunk"]
#             if chunk_content:  # 确保 chunk 非空
#                 yield f"data: {json.dumps({'type': 'token', 'content': chunk_content}, ensure_ascii=False)}\n\n"   
#             continue         
#     previous_yield_type="DONE" 
#     yield "data: [DONE]\n\n"


def _create_ai_message(parts: dict) -> AIMessage:
    sig = inspect.signature(AIMessage)
    valid_keys = set(sig.parameters)
    filtered = {k: v for k, v in parts.items() if k in valid_keys}
    return AIMessage(**filtered)


async def message_generator(
    user_input: Union[UserInput, PredictUserInput], agent_id: str = DEFAULT_AGENT
) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent.

    This is the workhorse method for the /stream endpoint.
    Supports both UserInput and PredictUserInput types.

    Args:
        user_input: Either UserInput or PredictUserInput object containing the user's request
        agent_id: The ID of the agent to use (defaults to DEFAULT_AGENT)

    Returns:
        An async generator yielding SSE formatted messages
    """
    
    agent: Pregel = get_agent(agent_id)
    kwargs, run_id = _parse_input(user_input)

    #上一次的yield类型
    previous_yield_type = "" 

    try:
        NEO_counts=0
        NEO_RESPONSE_counts=0
        # Process streamed events from the graph and yield messages over the SSE stream.
        async for stream_event in agent.astream(
            **kwargs, stream_mode=["updates", "messages", "custom"]
        ):
            if not isinstance(stream_event, tuple):
                continue
            stream_mode, event = stream_event
            # print(stream_mode, event)
            new_messages = []
            if stream_mode == "updates":
                for node, updates in event.items():
                    # A simple approach to handle agent interrupts.
                    # In a more sophisticated implementation, we could add
                    # some structured ChatMessage type to return the interrupt value.
                    if node == "__interrupt__":
                        interrupt: Interrupt
                        for interrupt in updates:
                            new_messages.append(AIMessage(content=interrupt.value))
                        continue
                    updates = updates or {}
                    update_messages = updates.get("messages", [])
                    # special cases for using langgraph-supervisor library
                    if node == "supervisor":
                        # Get only the last AIMessage since supervisor includes all previous messages
                        ai_messages = [msg for msg in update_messages if isinstance(msg, AIMessage)]
                        if ai_messages:
                            update_messages = [ai_messages[-1]]
                    if node in ("research_expert", "math_expert"):
                        # By default the sub-agent output is returned as an AIMessage.
                        # Convert it to a ToolMessage so it displays in the UI as a tool response.
                        msg = ToolMessage(
                            content=update_messages[0].content,
                            name=node,
                            tool_call_id="",
                        )
                        update_messages = [msg]
                    new_messages.extend(update_messages)
            
            if stream_mode == "custom":
                if isinstance(event, dict):
                    #  yield f"data: {json.dumps({'type': 'writer_token', 'content': event})}\n\n"
                    #  print(event)
                     dumps_event = json.dumps(event,ensure_ascii=False,)
                     yield f"data: {json.dumps({'type': 'writer_token', 'content': dumps_event})}\n\n"
                    #  print(dumps_event)
                elif event == "#NEO#":
                    NEO_counts += 1 
                    yield f"data: {json.dumps({'type': 'table', 'content': event})}\n\n"
                elif NEO_counts % 2 != 0:    
                    yield f"data: {json.dumps({'type': 'table', 'content': event})}\n\n"
                elif event == "#NEO_RESPONSE#":
                    NEO_RESPONSE_counts += 1 
                    yield f"data: {json.dumps({'type': 'response_table', 'content': event})}\n\n"
                elif NEO_RESPONSE_counts % 2 != 0:    
                    yield f"data: {json.dumps({'type': 'token', 'content': event})}\n\n"
                else:
                    previous_yield_type="token"
                    yield f"data: {json.dumps({'type': 'token', 'content': event})}\n\n"
                # print(event)

                # yield f"data: {json.dumps({'type': 'token', 'content': event})}\n\n"
                # new_messages = [event]

            # LangGraph streaming may emit tuples: (field_name, field_value)
            # e.g. ('content', <str>), ('tool_calls', [ToolCall,...]), ('additional_kwargs', {...}), etc.
            # We accumulate only supported fields into `parts` and skip unsupported metadata.
            # More info at: https://langchain-ai.github.io/langgraph/cloud/how-tos/stream_messages/
            processed_messages = []
            current_message: dict[str, Any] = {}
            for message in new_messages:
                if isinstance(message, tuple):
                    key, value = message
                    # Store parts in temporary dict
                    current_message[key] = value
                else:
                    # Add complete message if we have one in progress
                    if current_message:
                        processed_messages.append(_create_ai_message(current_message))
                        current_message = {}
                    processed_messages.append(message)

            # Add any remaining message parts
            if current_message:
                processed_messages.append(_create_ai_message(current_message))
            for message in processed_messages:
                try:
                    chat_message = langchain_to_chat_message(message)
                    chat_message.run_id = str(run_id)
                except Exception as e:
                    logger.error(f"Error parsing message: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'content': 'Unexpected error'})}\n\n"
                    continue
                # LangGraph re-sends the input message, which feels weird, so drop it
                if chat_message.type == "human" and chat_message.content == user_input.message:
                    continue
                if chat_message.type == "ai" and getattr(chat_message, "tool_calls", None) and previous_yield_type=="token":
                    # 先 yield 一个换行符消息
                    newline = "\n"
                    previous_yield_type="token" 
                    yield f"data: {json.dumps({'type': 'token', 'content': newline}, ensure_ascii=False)}\n\n"
                previous_yield_type="message" 

                yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"

            if stream_mode == "messages":
                if not user_input.stream_tokens:
                    continue
                msg, metadata = event
                if "skip_stream" in metadata.get("tags", []):
                    continue
                # For some reason, astream("messages") causes non-LLM nodes to send extra messages.
                # Drop them.
                if not isinstance(msg, AIMessageChunk):
                    continue
                content = remove_tool_calls(msg.content)
                if content:
                    # Empty content in the context of OpenAI usually means
                    # that the model is asking for a tool to be invoked.
                    # So we only print non-empty content.
                    previous_yield_type="token" 
                    # print(event)
                    yield f"data: {json.dumps({'type': 'token', 'content': convert_message_content_to_string(content)})}\n\n"
    except Exception as e:
        logger.error(f"Error in message generator: {e}")
        print(f"\n❌ ERROR in message_generator: {str(e)}")
        print("🔄 Full traceback:")
        import traceback
        traceback.print_exc()  # 直接打印完整的错误堆栈
        
        # 返回给客户端的错误信息（生产环境建议简化）
        error_detail = {
            "type": "error",
            "content": "Internal server error",
            # 开发时可以包含详细信息，生产环境应该移除
            "debug_info": str(e)  
        }
        yield f"data: {json.dumps(error_detail, ensure_ascii=False)}\n\n"

        # yield f"data: {json.dumps({'type': 'error', 'content': 'Internal server error'})}\n\n"
    finally:
        previous_yield_type="DONE"         
        yield "data: [DONE]\n\n"

#mRNA_research的接口
@app.post("/mRNA_research_stream", response_class=StreamingResponse, responses=_sse_response_example())
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
@app.post("/pmhc_affinity_prediction_stream", response_class=StreamingResponse, responses=_sse_response_example())
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

#neo_antigen_stream的接口
@app.post("/neo_antigen_stream", response_class=StreamingResponse, responses=_sse_response_example())
async def chat(user_input: UserInput, agent_id: str = NEO_ANTIGEN) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """
    logger.info(f"Received user_input: {user_input.dict()}")
    logger.info(f"Agent ID: {agent_id}")
    return StreamingResponse(
        message_generator(user_input, agent_id),
        media_type="text/event-stream",
    )

#predict_neo_antigen_stream的接口
@app.post("/predict_neo_antigen_stream", response_class=StreamingResponse, responses=_sse_response_example())
async def chat(user_input: PredictUserInput, agent_id: str = PREDICT_NEO_ANTIGEN) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """
    logger.info(f"Received user_input: {user_input.dict()}")
    logger.info(f"Agent ID: {agent_id}")
    return StreamingResponse(
        message_generator(user_input, agent_id),
        media_type="text/event-stream",
    )

#qa_predict_neo_stream的接口
@app.post("/qa_predict_neo_stream", response_class=StreamingResponse, responses=_sse_response_example())
async def chat(user_input: UserInput, agent_id: str = QA_PREDICT_NEO) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """
    logger.info(f"Received user_input: {user_input.dict()}")
    logger.info(f"Agent ID: {agent_id}")
    return StreamingResponse(
        message_generator(user_input, agent_id),
        media_type="text/event-stream",
    )

#对minio传来的文件进行描述
@app.post("/description", response_model=MinioResponse)
async def describe_text(request: MinioRequest):
    try:
        # 调用 LangChain 处理链
        result = fileDescriptionAgent.invoke(
            {
                "file_name": request.file_name,
                "file_content": request.file_content[0: min(256, len(request.file_content))]
            }
        )
        # 返回分析结果
        return MinioResponse(file_description = result.content)
    except Exception as e:
        # 捕获异常并返回错误信息
        raise HTTPException(status_code=500, detail=str(e))

#删除graph中图的状态
@app.delete("/delete_thread/{thread_id}")
async def reset_thread(thread_id: str):
    try:
        agents = get_all_agents()
        for agent in agents:
            await agent.graph.checkpointer.adelete_thread(thread_id)
        return {"status": "success", "message": f"Thread {thread_id} 已清除"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"清除失败: {str(e)}")

#处理病人信息结构化的接口
@app.post("/extract_patient_info", response_model=PatientInfoResponse)
async def process_patient_info(request: PatientInfoRequest):
    try:
        # 调用结构化处理模型
        result = PatientInfoDescriptionAgent.invoke({"patient_info":request.patient_info})
        # 返回结构化后的信息
        return PatientInfoResponse(structured_info=result.model_dump())
    except Exception as e:
        logger.error(f"处理病人信息时发生错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))
