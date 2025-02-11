import os
import pandas as pd
import streamlit as st
import uuid

from langchain_community.chat_message_histories import StreamlitChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from PIL import Image
from utils.st_callable_util import get_streamlit_cb  # Utility function to get a Streamlit callback handler with context

from config import CONFIG_YAML
from agent.graph import GRAPH

from utils.log import logger
from utils.translate_agent import TranslationAgent

MODEL_NAME = CONFIG_YAML["LLM"]["model_name"]
TEMPER = CONFIG_YAML["LLM"]["temperature"]

UPLOAD_DIR = CONFIG_YAML["TOOL"]["upload_dir"]

#获取api加载模型工具
llm_api_key = os.getenv("OPENAI_API_KEY") 

logo = Image.open("assets/molly_icon.png")
st.set_page_config(page_title="Molly", page_icon=logo)

# translator
trans_agent = TranslationAgent()

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

#tools = agent.tools

#tool_list = pd.Series(
#    {f"✅ {t.name}":t.description for t in tools}
#).reset_index()
#tool_list.columns = ['Tool', 'Description']

# sidebar
with st.sidebar:
    medcrow_logo = Image.open('assets/molly.png')
    st.image(medcrow_logo)

    st.markdown('---')
    st.header("upload files")
    uploaded_files = st.file_uploader("choose file", type=["fsa"], accept_multiple_files=True)
    if uploaded_files:
        st.success("File uploaded successfully!")
        # 保存上传的文件到指定路径
        for uploaded_file in uploaded_files:
            file_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
        st.write("Uploaded file saved!")

    saved_files = os.listdir(UPLOAD_DIR)
    # 提供选中文件功能
    if saved_files:
        selected_file_name = st.selectbox("选择一个文件", saved_files)
        selected_file_name = UPLOAD_DIR + selected_file_name
    # Display available tools
#    st.markdown(f"# {len(tool_list)} available tools")
#    st.dataframe(
#        tool_list,
#        use_container_width=True,
#        hide_index=True,
#        height=200
#    )

#message处理
if "messages" not in st.session_state:
    st.session_state.messages = []
if 'thread_id' not in st.session_state:
    # 生成一个随机的 UUID
    full_uuid = uuid.uuid4()
    # 将 UUID 转换为字符串并取前 4 个字符
    thread_id = str(full_uuid)[:4]
    st.session_state['thread_id'] = st.query_params.get('thread_id', thread_id)

# Ensure input counter is set
if 'input_counter' not in st.session_state:
    st.session_state['input_counter'] = 0

# Set up memory
msgs = StreamlitChatMessageHistory(key="messages")
if len(msgs.messages) == 0:
    msgs.add_ai_message("How can I help you?")

# Render current messages from StreamlitChatMessageHistory
for msg in msgs.messages:
    if not isinstance(msg, ToolMessage): 
        st.chat_message(msg.type).write(msg.content)    
    else:
        st.markdown('```\n'+msg.content+'\n```')
    #assert msg.type in ["human", "ai"]
    # assert msg.type in ["human", "assistant"]

# takes new input in chat box from user and invokes the graph
if prompt := st.chat_input():
    st.session_state.messages.append(HumanMessage(content=prompt))
    st.chat_message("user").write(prompt)

    # Process the AI's response and handles graph events using the callback mechanism
    with st.chat_message("assistant"):
        msg_placeholder = st.empty()  # Placeholder for visually updating AI's response after events end
        # create a new placeholder for streaming messages and other events, and give it context
        st_callback = get_streamlit_cb(st.empty())
        logger.info(f"Current selected file name: {selected_file_name}")
        agent_config = {
            "configurable": {                               
                "thread_id": st.session_state.get("thread_id", "xxx"),
                "input_filename": selected_file_name
            }, 
            "callbacks": [st_callback]
        }
        response = GRAPH.invoke(
            {
                "messages": [msg for msg in st.session_state.messages if not isinstance(msg, ToolMessage)],
            }, 
            config=agent_config
        )
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
                st.markdown('```\n'+contents+'\n```')
                st.session_state.messages.append(
                    ToolMessage(content=contents, tool_call_id=last_second_call_id)
                )  # Add that last message to the st_message_state
        else:
            st.session_state.messages.append(AIMessage(content=last_msg.content))  # Add that last message to the st_message_state
            msg_placeholder.write(last_msg.content) # visually refresh the complete response after the callback container
