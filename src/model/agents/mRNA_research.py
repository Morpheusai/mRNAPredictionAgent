import aiosqlite
from datetime import datetime
from typing import Literal

from langchain_community.tools import DuckDuckGoSearchResults, OpenWeatherMapQueryRun
from langchain_community.utilities import OpenWeatherMapAPIWrapper
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from utils.log import logger

from src.model.agents.tools import mRNAResearchAndProduction
from src.model.agents.tools import NetMHCpan
from src.model.agents.tools import ESM3
from .core import get_model  # 相对导入
import sys
from pathlib import Path
current_file = Path(__file__).resolve()
project_root = current_file.parents[3]  # 向上回溯 4 层目录：src/model/agents/tools → src/model/agents → src/model → src → 项目根目录
                                        
# 将项目根目录添加到 sys.path
sys.path.append(str(project_root))
from config import CONFIG_YAML


class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.

    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """


tools = [mRNAResearchAndProduction, NetMHCpan, ESM3]

raw_instructions = CONFIG_YAML["PROMPT"]["instructions"]



# current_date = datetime.now().strftime("%B %d, %Y")



def wrap_model(model: BaseChatModel, file_instructions: str) -> RunnableSerializable[AgentState, AIMessage]:
    model = model.bind_tools(tools)
    #导入prompt
    instructions = raw_instructions.format(FILE_INSTRUCYIONS=file_instructions)
    print(instructions)
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=instructions)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | model


async def acall_model(state: AgentState, config: RunnableConfig) -> AgentState:
    m = get_model(config["configurable"].get("model", None))
    #添加文件到system token里面
    file_list = config["configurable"].get("file_list", None)
    # 处理文件列表
    file_instructions = ""
    if file_list:
        for conversation in file_list:
            for file in conversation.files:
                file_instructions += f'file name: "{file.file_name}", file content: "{file.file_content}";\n'

    model_runnable = wrap_model(m,file_instructions)
    response = await model_runnable.ainvoke(state, config)
    return {"messages": [response]}

async def _parser(state: AgentState, config: RunnableConfig):
    messages = state["messages"]
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        # 处理所有工具调用
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_call_id = tool_call["id"]
            tool_call_netmhcpan_input=tool_call["args"].get("input_filecontent")
            tool_call_esm3_input=tool_call["args"].get("protein_sequence")

            # 检查是否已经存在相同 tool_call_id 的 ToolMessage
            if any(isinstance(msg, ToolMessage) and msg.tool_call_id == tool_call_id for msg in messages):
                continue  # 如果已经存在，跳过添加
            if tool_name == "NetMHCpan":
                input_filename = tool_call_netmhcpan_input
                func_result = await NetMHCpan.ainvoke(
                    {
                        "input_filecontent": input_filename
                    }
                )
                logger.info(f"NetMHCpan result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                messages.append(tool_msg)
                
            elif tool_name == "mRNAResearchAndProduction":
                func_result = await mRNAResearchAndProduction.ainvoke(
                    {
                        "input": "mRNA疫苗的研究生产过程"
                    }
                )
                logger.info(f"Neoantigen result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
            elif tool_name == "ESM3":
                func_result = await ESM3.ainvoke(
                    {
                        "protein_sequence" : tool_call_esm3_input
                    }
                )
                logger.info(f"ESM3 result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                messages.append(tool_msg)
    return {"messages": [tool_msg]}

# Define the graph
agent = StateGraph(AgentState)
agent.add_node("model", acall_model)
agent.add_node("parserNode", _parser)
agent.set_entry_point("model")

agent.add_edge("parserNode", END)

def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise TypeError(f"Expected AIMessage, got {type(last_message)}")
    if last_message.tool_calls:
        return "tools"
    return "done"


agent.add_conditional_edges("model", pending_tool_calls, {"tools": "parserNode", "done": END})


async def compile_mRNA_research():
    conn = await aiosqlite.connect("checkpoints.sqlite")
    mRNA_research = agent.compile(checkpointer=AsyncSqliteSaver(conn))
    return mRNA_research, conn
