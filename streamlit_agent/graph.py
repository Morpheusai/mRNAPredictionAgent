import aiosqlite

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver 
from typing import Literal,Optional

from src.model.agents.tools import mRNAResearchAndProduction
from src.model.agents.tools import NetMHCpan
from src.model.agents.tools import ESM3
from src.model.agents.tools import NetMHCstabpan
from src.model.agents.tools import FastaFileProcessor
from src.model.agents.tools.NetMHCPan.extract_min_affinity import extract_min_affinity_peptide
from src.utils.log import logger
from src.model.agents.core import get_model  # 相对导入
from src.model.agents.core.demo_prompts import MRNA_AGENT_PROMPT, FILE_LIST, NETMHCPAN_RESULT, ESM3_RESULT, NETMHCSTABPAN_RESULT, OUTPUT_INSTRUCTIONS


class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.
    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """
    netmhcpan_result: Optional[str]=None
    esm3_result: Optional[str]=None
    netmhcstabpan_result: Optional[str]=None

TOOLS = [mRNAResearchAndProduction, NetMHCpan, ESM3, FastaFileProcessor, NetMHCstabpan]       


def wrap_model(model: BaseChatModel, file_instructions: str) -> RunnableSerializable[AgentState, AIMessage]:
    model = model.bind_tools(TOOLS)
    #导入prompt
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=file_instructions)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | model


async def modelNode(state: AgentState, config: RunnableConfig) -> AgentState:
    m = get_model(
        config["configurable"].get("model", None),
        config["configurable"].get("temperature", None),
        config["configurable"].get("max_tokens", None),
        config["configurable"].get("base_url", None),
        config["configurable"].get("frequency_penalty", None),
        )
    #添加文件到system token里面
    file_list = config["configurable"].get("file_list", None)
    # 处理文件列表
    instructions = MRNA_AGENT_PROMPT                
    if file_list:
        for conversation_file in file_list:
            # 获取 files 列表
            files = conversation_file.get("files", [])
            for file in files:
                # 通过字典键访问文件信息
                file_name = file.get("file_name", "未知文件名")
                file_path = file.get("file_path", "未知路径")
                file_content = file.get("file_content", "未知内容")
                file_desc = file.get("file_desc", "未知描述")
                
                # 构建文件说明
                file_instructions = (
                    f"*上传文件名*: {file_name} \n"
                    f"*上传的文件路径*: {file_path} \n"
                    f"*上传的文件内容*: {file_content} \n"
                    f"*上传的文件描述*: {file_desc} \n"
                )                
                file_list_content = FILE_LIST.format(file_list=file_instructions)
                netmhcpan_result = NETMHCPAN_RESULT.format(netmhcpan_result=state.get("netmhcpan_result"))
                esm3_result = ESM3_RESULT.format(esm3_result=state.get("esm3_result"))
                netmhcstabpan_result = NETMHCSTABPAN_RESULT.format(netmhcstabpan_result=state.get("netmhcstabpan_result"))
                instructions += file_list_content
                instructions += netmhcpan_result
                instructions +=esm3_result
                instructions +=netmhcstabpan_result
                instructions +=OUTPUT_INSTRUCTIONS
 

    
    model_runnable = wrap_model(m,instructions)
    response = await model_runnable.ainvoke(state, config)
    # print(state)
    return {"messages": [response]}

async def should_continue(state: AgentState, config: RunnableConfig):
    messages = state["messages"]
    last_message = messages[-1]
    tmp_tool_msg = []
    netmhcpan_result=""
    esm3_result=""
    netmhcstabpan_result=""
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        # 处理所有工具调用
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_call_id = tool_call["id"]
            

            # 检查是否已经存在相同 tool_call_id 的 ToolMessage
            if any(isinstance(msg, ToolMessage) and msg.tool_call_id == tool_call_id for msg in messages):
                continue  # 如果已经存在，跳过添加
            if tool_name == "NetMHCpan":
                input_file = tool_call["args"].get("input_file")
                mhc_allele=tool_call["args"].get("mhc_allele","HLA-A02:01")
                high_threshold_of_bp=tool_call["args"].get("high_threshold_of_bp",0.5)
                low_threshold_of_bp=tool_call["args"].get("low_threshold_of_bp",2.0)
                peptide_length=tool_call["args"].get("peptide_length","9")
                func_result = await NetMHCpan.ainvoke(
                    {
                        "input_file": input_file,
                        "mhc_allele": mhc_allele,
                        "high_threshold_of_bp": high_threshold_of_bp,
                        "low_threshold_of_bp": low_threshold_of_bp,
                        "peptide_length":peptide_length
                    }
                )
                # netmhcpan_result=extract_min_affinity_peptide(func_result)
                netmhcpan_result=func_result
                logger.info(f"NetMHCpan result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)

            elif tool_name == "FastaFileProcessor":
                input_file=tool_call["args"].get("input_file")
                func_result = await FastaFileProcessor.ainvoke(
                    {
                        "input_file": input_file
                    }
                )
                logger.info(f"FastaFileProcessor result: {func_result}")
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
                tool_call_esm3_input=tool_call["args"].get("protein_sequence")
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

            elif tool_name == "NetMHCstabpan":
                input_file = tool_call["args"].get("input_file")
                mhc_allele=tool_call["args"].get("mhc_allele","HLA-A02:01")
                high_threshold_of_bp=tool_call["args"].get("high_threshold_of_bp",0.5)
                low_threshold_of_bp=tool_call["args"].get("low_threshold_of_bp",2.0)
                peptide_length=tool_call["args"].get("peptide_length","9")
                func_result = await NetMHCstabpan.ainvoke(
                    {
                        "input_file": input_file,
                        "mhc_allele": mhc_allele,
                        "high_threshold_of_bp": high_threshold_of_bp,
                        "low_threshold_of_bp": low_threshold_of_bp,
                        "peptide_length":peptide_length
                    }
                )
                netmhcstabpan_result=func_result

                logger.info(f"NetMHCstabpan result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)
    return {
        "messages": tmp_tool_msg,
        "netmhcpan_result":netmhcpan_result,
        "esm3_result":esm3_result,
        "netmhcstabpan_result":netmhcstabpan_result,
        }


# Define the graph
DemoMrnaResearchAgent = StateGraph(AgentState)
DemoMrnaResearchAgent.add_node("modelNode", modelNode)
DemoMrnaResearchAgent.add_node("should_continue", should_continue)
DemoMrnaResearchAgent.set_entry_point("modelNode")

DemoMrnaResearchAgent.add_edge("should_continue", "modelNode")

def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise TypeError(f"Expected AIMessage, got {type(last_message)}")
    if last_message.tool_calls:
        return "tools"
    return "done"


DemoMrnaResearchAgent.add_conditional_edges("modelNode", pending_tool_calls, {"tools": "should_continue", "done": END})


GRAPH_MEMORY = MemorySaver()
GRAPH = DemoMrnaResearchAgent.compile(
    checkpointer=GRAPH_MEMORY
)