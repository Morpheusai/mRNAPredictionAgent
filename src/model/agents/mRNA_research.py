import aiosqlite
from datetime import datetime
from typing import Literal,Optional

from langchain_community.tools import DuckDuckGoSearchResults, OpenWeatherMapQueryRun
from langchain_community.utilities import OpenWeatherMapAPIWrapper
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph
# from langgraph.managed import RemainingSteps
# from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from utils.log import logger

from src.model.agents.tools import mRNAResearchAndProduction
from src.model.agents.tools import NetMHCpan
from src.model.agents.tools import ESM3
from src.model.agents.tools import Validate_Fas
from src.model.agents.tools import Correct_Fas
from src.model.agents.utils import extract_min_affinity_peptide
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
    netmhcpan_result: Optional[str]=None
    esm3_result: Optional[str]=None

tools = [mRNAResearchAndProduction, NetMHCpan, ESM3, Validate_Fas, Correct_Fas]

NETMHCPAN_PROMPT = CONFIG_YAML["PROMPT"]["NETMHCPAN_PROMPT"]
FILE_LIST = CONFIG_YAML["PROMPT"]["FILE_LIST"]
NETMHCPAN_RESULT=CONFIG_YAML["PROMPT"]["NETMHCPAN_RESULT"]
ESM3_RESULT=CONFIG_YAML["PROMPT"]["ESM3_RESULT"]
OUTPUT_INSTRUCTIONS=CONFIG_YAML["PROMPT"]["OUTPUT_INSTRUCTIONS"]
# current_date = datetime.now().strftime("%B %d, %Y")



def wrap_model(model: BaseChatModel, file_instructions: str) -> RunnableSerializable[AgentState, AIMessage]:
    model = model.bind_tools(tools)
    #导入prompt
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=file_instructions)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | model


async def modelNode(state: AgentState, config: RunnableConfig) -> AgentState:
    m = get_model(config["configurable"].get("model", None))
    #添加文件到system token里面
    file_list = config["configurable"].get("file_list", None)
    # 处理文件列表
    instructions = NETMHCPAN_PROMPT
    if file_list:
        for conversation_file in file_list:
            for file in conversation_file.files:
                file_name = file.file_name
                file_path = file.file_path
                file_content = file.file_content
                file_desc = file.file_desc
                file_instructions = f"*上传文件名*: {file_name} \n" + \
                                    f"*上传的文件路径*: {file_path} \n" + \
                                    f"*上传的文件内容*: {file_content} \n" + \
                                    f"*上传的文件描述*: {file_desc} \n"
                file_list_content = FILE_LIST.format(file_list=file_instructions)
                netmhcpan_result = NETMHCPAN_RESULT.format(netmhcpan_result=state.get("netmhcpan_result"))
                esm3_result = ESM3_RESULT.format(esm3_result=state.get("esm3_result"))
                instructions += file_list_content
                instructions += netmhcpan_result
                instructions +=esm3_result
                instructions +=OUTPUT_INSTRUCTIONS

    print(instructions)
    
    model_runnable = wrap_model(m,instructions)
    response = await model_runnable.ainvoke(state, config)
    return {"messages": [response]}

async def should_continue(state: AgentState, config: RunnableConfig):
    messages = state["messages"]
    last_message = messages[-1]
    tmp_tool_msg = []
    netmhcpan_result=""
    esm3_result=""
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        # 处理所有工具调用
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_call_id = tool_call["id"]
            tool_call_input_fasta_filepath=tool_call["args"].get("input_fasta_filepath")
            tool_call_netmhcpan_mhc_allele=tool_call["args"].get("mhc_allele","HLA-A02:01")
            tool_call_netmhcpan_high_threshold_of_bp=tool_call["args"].get("high_threshold_of_bp",0.5)
            tool_call_netmhcpan_low_threshold_of_bp=tool_call["args"].get("low_threshold_of_bp",2.0)
            tool_call_netmhcpan_peptide_length=tool_call["args"].get("peptide_length","9")
            tool_call_Validate_Correct_input=tool_call["args"].get("input_file")
            tool_call_esm3_input=tool_call["args"].get("protein_sequence")

            # 检查是否已经存在相同 tool_call_id 的 ToolMessage
            if any(isinstance(msg, ToolMessage) and msg.tool_call_id == tool_call_id for msg in messages):
                continue  # 如果已经存在，跳过添加
            if tool_name == "NetMHCpan":
                input_fasta_filepath = tool_call_input_fasta_filepath
                mhc_allele=tool_call_netmhcpan_mhc_allele
                high_threshold_of_bp=tool_call_netmhcpan_high_threshold_of_bp
                low_threshold_of_bp=tool_call_netmhcpan_low_threshold_of_bp
                peptide_length=tool_call_netmhcpan_peptide_length
                func_result = await NetMHCpan.ainvoke(
                    {
                        "input_fasta_filepath": input_fasta_filepath,
                        "mhc_allele": mhc_allele,
                        "high_threshold_of_bp": high_threshold_of_bp,
                        "low_threshold_of_bp": low_threshold_of_bp,
                        "peptide_length":peptide_length

                    }
                )
                netmhcpan_result=extract_min_affinity_peptide(func_result)
                logger.info(f"NetMHCpan result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)

            elif tool_name == "Validate_Fas":
                input_file=tool_call_Validate_Correct_input
                func_result = await Validate_Fas.ainvoke(
                    {
                        "input_file": input_file
                    }
                )
                
                logger.info(f"Validate_Fas result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)            
                
            elif tool_name == "Correct_Fas":
                input_file=tool_call_Validate_Correct_input
                func_result = await Correct_Fas.ainvoke(
                    {
                        "input_file": input_file
                    }
                )
                
                logger.info(f"Correct_Fas result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)

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
                tmp_tool_msg.append(tool_msg)


            elif tool_name == "ESM3":
                func_result = await ESM3.ainvoke(
                    {
                        "protein_sequence" : tool_call_esm3_input
                    }
                )
                logger.info(f"ESM3 result: {func_result}")
                esm3_result=func_result

                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)
    return {"messages": tmp_tool_msg,"netmhcpan_result":netmhcpan_result,"esm3_result":esm3_result}


# Define the graph
agent = StateGraph(AgentState)
agent.add_node("modelNode", modelNode)
agent.add_node("should_continue", should_continue)
agent.set_entry_point("modelNode")

agent.add_edge("should_continue", END)

def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise TypeError(f"Expected AIMessage, got {type(last_message)}")
    if last_message.tool_calls:
        return "tools"
    return "done"


agent.add_conditional_edges("modelNode", pending_tool_calls, {"tools": "should_continue", "done": END})


async def compile_mRNA_research():
    conn = await aiosqlite.connect("checkpoints.sqlite")
    mRNA_research = agent.compile(checkpointer=AsyncSqliteSaver(conn))
    return mRNA_research, conn
