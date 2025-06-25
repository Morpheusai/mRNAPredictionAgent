import asyncio
import os
import pandas as pd
import streamlit as st
import uuid

from langchain_community.chat_message_histories import StreamlitChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from PIL import Image
from utils.st_callable_util import get_streamlit_cb  # Utility function to get a Streamlit callback handler with context

from graph import GRAPH
from src.schema.models import OpenAIModelName
from src.utils.log import logger
# from utils.translate_agent import TranslationAgent

MODEL_NAME = "gpt-4o"
TEMPER = 0.1

UPLOAD_DIR = "/mnt/workspace/dev/ljs/demo_agent/tmp"

# 获取 API 加载模型工具
llm_api_key = os.getenv("OPENAI_API_KEY")

logo = Image.open("assets/molly_icon.png")
st.set_page_config(page_title="Molly", page_icon=logo)

# translator
# trans_agent = TranslationAgent()

# 设置侧边栏样式
st.markdown(
    """
    <style>
    [data-testid="stSidebar"][aria-expanded="true"]{
        min-width: 350px;
        max-width: 350px;
    }
    """,
    unsafe_allow_html=True,
)

# tools = agent.tools
# tool_list = pd.Series(
#    {f"✅ {t.name}":t.description for t in tools}
# ).reset_index()
# tool_list.columns = ['Tool', 'Description']

# 侧边栏
with st.sidebar:
    medcrow_logo = Image.open('assets/molly.png')
    st.image(medcrow_logo)

    st.markdown('---')
    st.header("上传文件")
    uploaded_files = st.file_uploader("选择文件", type=["fsa"], accept_multiple_files=True)
    if uploaded_files:
        st.success("文件上传成功！")
        # 保存上传的文件到指定路径
        for uploaded_file in uploaded_files:
            file_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
        st.write("上传的文件已保存！")

    saved_files = os.listdir(UPLOAD_DIR)
    # 提供选中文件功能
    if saved_files:
        selected_file_name = st.selectbox("选择一个文件", saved_files)
        selected_file_name = UPLOAD_DIR + selected_file_name

# 初始化会话状态
if "messages" not in st.session_state:
    st.session_state.messages = []
if 'thread_id' not in st.session_state:
    # 生成一个随机的 UUID
    full_uuid = uuid.uuid4()
    # 将 UUID 转换为字符串并取前 4 个字符
    thread_id = str(full_uuid)[:4]
    st.session_state['thread_id'] = st.query_params.get('thread_id', thread_id)

# 确保输入计数器已设置
if 'input_counter' not in st.session_state:
    st.session_state['input_counter'] = 0

# 设置消息历史
msgs = StreamlitChatMessageHistory(key="messages")
if len(msgs.messages) == 0:
    msgs.add_ai_message("How can I help you?")

# =========================== 修改部分 ===========================
# 渲染所有历史消息
for msg in st.session_state.messages:
    if isinstance(msg, HumanMessage):
        st.chat_message("user").write(msg.content)
    elif isinstance(msg, AIMessage):
        st.chat_message("assistant").write(msg.content)
    elif isinstance(msg, ToolMessage):
        st.markdown('```\n' + msg.content + '\n```')

# 处理用户输入并调用图
if prompt := st.chat_input():
    st.session_state.messages.append(HumanMessage(content=prompt))
    st.chat_message("user").write(prompt)

    # 处理 AI 的响应并使用回调机制处理图事件
    with st.chat_message("assistant"):
        msg_placeholder = st.empty()  # 用于在事件结束后视觉更新 AI 的响应
        # 创建一个新的占位符用于流式消息和其他事件，并为其提供上下文
        st_callback = get_streamlit_cb(st.empty())
        # logger.info(f"当前选择的文件名: {selected_file_name}")
        agent_config = {
            "configurable": {                               
                "thread_id": st.session_state.get("thread_id", "xxx"),
                "model": OpenAIModelName.GPT_4O, 
                "temperature": TEMPER, 
                "max_tokens": OpenAIModelName.MAX_TOKENS,
                "base_url": OpenAIModelName.BASE_URL,
                "frequency_penalty": OpenAIModelName.FREQUENCY_PENALTY,
                "file_list": [  
                    {
                        "conversation_id": "ae1b2c3d4-1234-5678-90ef-123456789ab",
                        "files": [
                            {
                                "file_name": "test2.fsa",
                                "file_content": "序列肽段",
                                "file_path": "minio://molly/14d14a2e-a2bc-45aa-a033-f27fb4198357_test.fsa",
                                "file_desc": "序列肽段"
                            }
                        ]
                    }
                ]
            }, 
            "callbacks": [st_callback]
        }
        response = asyncio.run(GRAPH.ainvoke(
            {
                "messages": [msg for msg in st.session_state.messages],
            }, 
            config=agent_config
        ))
        last_msg = response["messages"][-1]
        if isinstance(last_msg, ToolMessage):
            last_second_msg = response["messages"][-2]
            last_second_call_id = last_second_msg.tool_calls[0]["id"]
            if last_second_msg.tool_calls[0]["name"] == "NetMHCpan":   
                state_values = GRAPH.get_state(agent_config).values
                logger.info(f"ST: {state_values}")
                func_result = state_values.get("net_c4_result", "some error happens, please check!")
                logger.info(f"NetMHCpan Result:\n {func_result}")
                with open(func_result, "r") as fin:
                    content = fin.readlines()
                contents = "".join(content)
                st.markdown('```\n' + contents + '\n```')
                # =========================== 修改部分 ===========================
                st.session_state.messages.append(
                    ToolMessage(content=contents, tool_call_id=last_second_call_id)
                )  # 将最后的消息添加到会话状态中
                # =========================== 修改结束 ===========================
        else:
            # =========================== 修改部分 ===========================
            st.session_state.messages.append(AIMessage(content=last_msg.content))  # 将最后的消息添加到会话状态中
            msg_placeholder.write(last_msg.content)  # 在回调容器后视觉刷新完整响应
            # =========================== 修改结束 ===========================