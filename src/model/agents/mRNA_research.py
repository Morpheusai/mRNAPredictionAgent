import aiosqlite

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from typing import Literal,Optional

from src.model.agents.tools import mRNAResearchAndProduction
from src.model.agents.tools import NetMHCpan
from src.model.agents.tools import ESM3
from src.model.agents.tools import NetMHCstabpan
from src.model.agents.tools import FastaFileProcessor
from src.model.agents.tools import ExtractPeptide
from src.model.agents.tools import pMTnet
from src.model.agents.tools import NetChop
from src.model.agents.tools import Prime
from src.model.agents.tools import NetTCR
from src.model.agents.tools import NetCTLpan
from src.model.agents.tools import PISTE
from src.model.agents.tools import ImmuneApp
from src.model.agents.tools.netmhcpan_Tool.extract_min_affinity import extract_min_affinity_peptide
from src.utils.log import logger

from .core import get_model  # 相对导入
from .core.prompts import (
    MRNA_AGENT_PROMPT,
    FILE_LIST,
    NETMHCPAN_RESULT,
    ESM3_RESULT,
    NETMHCSTABPAN_RESULT,
    OUTPUT_INSTRUCTIONS,
    PMTNET_RESULT,
    NETCTLpan_RESULT,
    PISTE_RESULT,
    ImmuneApp_RESULT,
    NETCHOP_RESULT, 
    PRIME_RESULT,
    NETTCR_RESULT
)


class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.
    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """
    netmhcpan_result: Optional[str]=None
    esm3_result: Optional[str]=None
    netmhcstabpan_result: Optional[str]=None
    pmtnet_result: Optional[str]=None
    netchop_result: Optional[str]=None
    prime_result: Optional[str]=None
    nettcr_result: Optional[str]=None
    netctlpan_result: Optional[str]=None
    piste_result: Optional[str]=None
    immuneapp_result: Optional[str]=None

TOOLS = [
    mRNAResearchAndProduction,
    NetMHCpan,
    ESM3,
    FastaFileProcessor,
    NetMHCstabpan,
    ExtractPeptide,
    pMTnet,
    NetCTLpan,
    PISTE,
    ImmuneApp,
    NetChop, 
    Prime, 
    NetTCR
]
    
TOOL_TEMPLATES = {
    "netmhcpan_result": NETMHCPAN_RESULT,
    "esm3_result": ESM3_RESULT,
    "netmhcstabpan_result": NETMHCSTABPAN_RESULT,
    "pmtnet_result": PMTNET_RESULT,
    "netctlpan_result": NETCTLpan_RESULT,
    "piste_result": PISTE_RESULT,
    "immuneapp_result": ImmuneApp_RESULT,
}

def wrap_model(model: BaseChatModel, file_instructions: str) -> RunnableSerializable[AgentState, AIMessage]:
    model = model.bind_tools(TOOLS)
    #导入prompt
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=file_instructions)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | model

def format_file_info(file) -> str:
    return (
        f"*上传文件名*: {file.file_name}\n"
        f"*上传的文件路径*: {file.file_path}\n"
        f"*上传的文件内容*: {file.file_content}\n"
        f"*上传的文件描述*: {file.file_desc}\n"
    )

def format_tool_results(state: dict, tool_templates: dict) -> str:
    return "\n".join(
        template.format(**{key: state.get(key)})
        for key, template in tool_templates.items()
    )
    
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
            for file in conversation_file.files:
                file_info = FILE_LIST.format(file_list=format_file_info(file))
                tool_results = format_tool_results(state, TOOL_TEMPLATES)
                instructions += f"{file_info}\n{tool_results}\n{OUTPUT_INSTRUCTIONS}"
    
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
    pmtnet_result=""
    netchop_result=""
    prime_result=""
    nettcr_result=""
    netctlpan_result=""
    piste_result=""
    immuneapp_result=""
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
                netmhcpan_result=extract_min_affinity_peptide(func_result)

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
            elif tool_name == "ExtractPeptide":
                input_content = tool_call["args"].get("peptide_sequence")
                func_result = await ExtractPeptide.ainvoke(
                    {
                        "peptide_sequence": input_content
                    }
                )
                logger.info(f"ExtractPeptide result: {func_result}")
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
            elif tool_name == "pMTnet":
                input_file_dir = tool_call["args"].get("input_file_dir")
                func_result = await pMTnet.ainvoke(
                    {
                        "input_file_dir": input_file_dir
                    }
                )
                logger.info(f"pMTnet result: {func_result}")
                pmtnet_result=func_result
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)
                
            elif tool_name == "PISTE":
                input_file_dir = tool_call["args"].get("input_file_dir")
                model_name = tool_call["args"].get("model_name","random")
                threshold = tool_call["args"].get("threshold", 0.5)
                antigen_type = tool_call["args"].get("antigen_type","MT")
                func_result = await PISTE.ainvoke(
                    {
                        "input_file_dir": input_file_dir,
                        "model_name": model_name,
                        "threshold": threshold,
                        "antigen_type": antigen_type
                    }
                )
                logger.info(f"piste result: {func_result}")
                piste_result=func_result
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

            elif tool_name == "NetChop":
                input_file = tool_call["args"].get("input_file")
                cleavage_site_threshold=tool_call["args"].get("cleavage_site_threshold",0.5)
                func_result = await NetChop.ainvoke(
                    {
                        "input_file": input_file,
                        "cleavage_site_threshold": cleavage_site_threshold,
                    }
                )
                netchop_result=func_result

                logger.info(f"NetChop result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)         
            elif tool_name == "Prime":
                input_file = tool_call["args"].get("input_file")
                mhc_allele=tool_call["args"].get("mhc_allele","A0101")
                func_result = await Prime.ainvoke(
                    {
                        "input_file": input_file,
                        "mhc_allele": mhc_allele,
                    }
                )
                prime_result=func_result

                logger.info(f"Prime result: {func_result}")
                
            elif tool_name == "NetCTLpan":
                input_file = tool_call["args"].get("input_file")
                mhc_allele=tool_call["args"].get("mhc_allele","HLA-A02:01")
                weight_of_clevage=tool_call["args"].get("weight_of_clevage",0.225)
                weight_of_tap=tool_call["args"].get("weight_of_tap",0.025)
                peptide_length=tool_call["args"].get("peptide_length","9")
                func_result = await NetCTLpan.ainvoke(
                    {
                        "input_file": input_file,
                        "mhc_allele": mhc_allele,
                        "weight_of_clevage": weight_of_clevage,
                        "weight_of_tap": weight_of_tap,
                        "peptide_length":peptide_length
                    }
                )
                netctlpan_result=func_result
                logger.info(f"NetCTLpan result: {func_result}")
                tool_msg = ToolMessage(
                    content=func_result,
                    tool_call_id=tool_call_id,
                )
                tmp_tool_msg.append(tool_msg)       
            elif tool_name == "NetTCR":
                input_file = tool_call["args"].get("input_file")
                func_result = await NetTCR.ainvoke(
                    {
                        "input_file": input_file,
                    }
                )
                nettcr_result=func_result

                logger.info(f"NetTCR result: {func_result}")
                tmp_tool_msg.append(tool_msg)
            elif tool_name == "ImmuneApp":
                input_file_dir = tool_call["args"].get("input_file_dir")
                alleles=tool_call["args"].get("alleles","HLA-A*01:01,HLA-A*02:01,HLA-A*03:01,HLA-B*07:02")
                use_binding_score=tool_call["args"].get("use_binding_score",True)
                peptide_lengths=tool_call["args"].get("peptide_lengths",[8,9])
                func_result = await ImmuneApp.ainvoke(
                    {
                        "input_file_dir": input_file_dir,
                        "alleles": alleles,
                        "use_binding_score": use_binding_score,
                        "peptide_lengths": peptide_lengths,
                    }
                )
                immuneapp_result=func_result
                logger.info(f"ImmuneApp result: {func_result}")
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
        "pmtnet_result":pmtnet_result,
        "netchop_result":netchop_result,
        "prime_result":prime_result,
        "nettcr_result":nettcr_result,
        "piste_result": piste_result,
        "netctlpan_result":netctlpan_result,
        "immuneapp_result": immuneapp_result,
        }


# Define the graph
mrnaResearchAgent = StateGraph(AgentState)
mrnaResearchAgent.add_node("modelNode", modelNode)
mrnaResearchAgent.add_node("should_continue", should_continue)
mrnaResearchAgent.set_entry_point("modelNode")

mrnaResearchAgent.add_edge("should_continue", END)

def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise TypeError(f"Expected AIMessage, got {type(last_message)}")
    if last_message.tool_calls:
        return "tools"
    return "done"


mrnaResearchAgent.add_conditional_edges("modelNode", pending_tool_calls, {"tools": "should_continue", "done": END})


async def compile_mRNA_research():
    conn = await aiosqlite.connect("checkpoints.sqlite")
    mRNA_research = mrnaResearchAgent.compile(checkpointer=AsyncSqliteSaver(conn))
    return mRNA_research, conn
