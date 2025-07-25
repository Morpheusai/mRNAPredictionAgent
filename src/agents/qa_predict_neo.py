from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from typing import Literal,Optional

from src.utils.log import logger

from src.core import get_model, settings
from .prompt.pMHC_affinity_prediction_prompts import (
    MRNA_AGENT_PROMPT, 
)

class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.
    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """

TOOLS = []       

def wrap_model(model: BaseChatModel, file_instructions: str) -> RunnableSerializable[AgentState, AIMessage]:
    model = model.bind_tools(TOOLS)
    #导入prompt
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=file_instructions)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | model

async def modelNode(state: AgentState, config: RunnableConfig) -> AgentState:
    model = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    #添加文件到system token里面
    # file_list = config["configurable"].get("file_list", None)
    # 处理文件列表
    instructions = MRNA_AGENT_PROMPT
    # if file_list:
    #     for conversation_file in file_list:
    #         for file in conversation_file.files:
    #             file_name = file.file_name
    #             file_path = file.file_path
    #             file_content = file.file_content
    #             file_desc = file.file_desc
    #             file_instructions = f"*上传文件名*: {file_name} \n" + \
    #                                 f"*上传的文件路径*: {file_path} \n" + \
    #                                 f"*上传的文件内容*: {file_content} \n" + \
    #                                 f"*上传的文件描述*: {file_desc} \n"

    
    model_runnable = wrap_model(model, instructions)
    response = await model_runnable.ainvoke(state, config)
    # print(state)
    return {"messages": [response]}

# Define the graph
QAPredictNeoAgent = StateGraph(AgentState)
QAPredictNeoAgent.add_node("modelNode", modelNode)
QAPredictNeoAgent.set_entry_point("modelNode")

qa_predict_neo_research = QAPredictNeoAgent.compile(
    checkpointer = MemorySaver(), 
    store = InMemoryStore()
)