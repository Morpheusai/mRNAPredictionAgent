import os
import pandas as pd
import streamlit as st
import uuid

from langchain_community.chat_message_histories import StreamlitChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage
from PIL import Image
from utils.st_callable_util import get_streamlit_cb  # Utility function to get a Streamlit callback handler with context

from config import CONFIG_YAML
from agent.graph import invoke_our_graph

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
if 'session_id' not in st.session_state:
    st.session_state['session_id'] = st.query_params.get('session_id', [str(uuid.uuid4())])[0]  

# Ensure input counter is set
if 'input_counter' not in st.session_state:
    st.session_state['input_counter'] = 0

# Set up memory
msgs = StreamlitChatMessageHistory(key="messages")
if len(msgs.messages) == 0:
    msgs.add_ai_message("How can I help you?")

# Render current messages from StreamlitChatMessageHistory
for msg in msgs.messages:
    st.chat_message(msg.type).write(msg.content)    
    assert msg.type in ["human", "ai"]
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
                "input_filename": selected_file_name
            }, 
            "callbacks": [st_callback]
        }
        response = invoke_our_graph(
            st_messages=st.session_state.messages, 
            config=agent_config
        )
        last_msg = response["messages"][-1].content
        st.session_state.messages.append(AIMessage(content=last_msg))  # Add that last message to the st_message_state
        msg_placeholder.write(last_msg) # visually refresh the complete response after the callback container