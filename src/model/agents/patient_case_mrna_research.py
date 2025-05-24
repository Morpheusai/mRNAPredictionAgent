import aiosqlite

from pydantic import BaseModel, Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langgraph.types import Command
from typing import Literal, Any, Optional

from src.model.agents.tools import (
    NeoAntigenSelection
)
from src.utils.log import logger

from .core import get_model  # 相对导入
from .core.patient_case_mrna_prompts import (
    PatientCaseReportAnalysisPrompt,
)

class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.
    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """
    mhc_allele: str
    cdr3: str
    input_fsa_filename: str
    patient_case_summary: str

# Data model
class PatientCaseSummaryReport(BaseModel):
    """病例数据分析后的总结输出结果."""
    action: Literal["YES", "NO"] = Field(
        ...,
        description="结合病人的病例分析，是否适合mRNA疫苗治疗",
    )
    mhc_allele: str = Field(
        ...,
        description="病例中测结果中检测到的MHC allele",
    )
    cdr3: str = Field(
        ...,
        description="病例中测结果中检测到的CDR3序列",
    )
    input_fsa_filename: str = Field(
        ...,
        description="病人上传的fsa文件",
    )
    summary: str = Field(
        ...,
        description="病例分析后的总结",
    )

def wrap_model(
        model: BaseChatModel, 
        system_prompt: str,
        structure_model: bool = False,
        structure_output: Any = None
    ) -> RunnableSerializable[AgentState, AIMessage]:
    if structure_model:
        model = model.with_structured_output(schema=structure_output)
    #导入prompt
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=system_prompt)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | model

async def PatientCaseAnalysisNode(state: AgentState, config: RunnableConfig) -> AgentState:
    model = get_model(
        config["configurable"].get("model", None),
        config["configurable"].get("temperature", None),
        config["configurable"].get("max_tokens", None),
        config["configurable"].get("base_url", None),
        config["configurable"].get("frequency_penalty", None),
    )
    #添加文件到system token里面
    file_list = config["configurable"].get("file_list", None)
    # 处理文件列表
    patient_info = ""
    if file_list:
        for conversation_file in file_list:
            for file in conversation_file.files:
                file_name = file.file_name
                file_content = file.file_content
                file_desc = file.file_desc
                file_instructions = f"*上传文件名*: {file_name} \n" + \
                                    f"*上传的文件描述*: {file_desc} \n" + \
                                    f"*上传的文件内容*: {file_content} \n"
                patient_info += file_instructions
    system_prompt = PatientCaseReportAnalysisPrompt.format(
        patient_info = patient_info,
    )
    logger.info(f"patient analysis prompt: {system_prompt}")
    model_runnable = wrap_model(
        model, 
        system_prompt, 
        structure_model = True, 
        structure_output = PatientCaseSummaryReport
    )
    response = await model_runnable.ainvoke(state, config)
    logger.info(f"patient analysis llm response: {system_prompt}")
    # TODO, debug
    action = response.content["action"]
    if action == "NO":
        return Command(
            update = {
                "messages": AIMessage(content="当前病人不适合做mRNA研究")
            },
            goto = END
        )
    mhc_allele = response.content["mhc_allele"]
    cdr3 = response.content["cdr3"]
    input_fsa_filename = response.content["input_fsa_filename"]
    summary = response.content["summary"]

    # 返回结果
    return Command(
        update = {
            "mhc_allele": mhc_allele,
            "cdr3": cdr3,
            "input_fsa_filename": input_fsa_filename,
            "patient_case_summary": summary
        },
        goto = "NetChopNode"
    )

async def mRNADesginNode(state: AgentState, config: RunnableConfig):
    
    input_fsa_filename = state["input_fsa_filename"]
    mhc_allele = state["mhc_allele"]
    cdr3 = state["cdr3"]

    # 1. 通过state参数构建NeoAntigenResearch工具输入参数
    result = await NeoAntigenSelection.arun(
        input_file = input_fsa_filename,
        mhc_allele = mhc_allele,
        cdr3_sequence = cdr3
    )

    return Command(
        update = {
            "mhc_allele": mhc_allele,
            "cdr3": cdr3,
            "input_fsa_filename": input_fsa_filename,
            "patient_case_summary": summary
        },
        goto = "NetMHCPanNode"
    )

async def CaseReportNode(state: AgentState, config: RunnableConfig):
    # 1. 通过state参数构建BigMHCNode工具输入参数   
    # 2. 调用BigMHCNode工具
    # 3. 调用大模型分析调用结果，看是否继续：END -> CDR3Node
    return

# Define the graph
PatientCaseMrnaAgent = StateGraph(AgentState)
PatientCaseMrnaAgent.add_node("patient_case_analysis", PatientCaseAnalysisNode)
PatientCaseMrnaAgent.add_node("mrna_desgin_node", mRNADesginNode)
PatientCaseMrnaAgent.add_node("case_report", CaseReportNode)
PatientCaseMrnaAgent.set_entry_point("patient_case_analysis")

async def patient_case_mRNA_research_nodes():
    patient_case_mRNA_research_nodes_conn = await aiosqlite.connect("checkpoints.sqlite")
    patient_case_mRNA_research_nodes = PatientCaseMrnaAgent.compile(checkpointer=AsyncSqliteSaver(patient_case_mRNA_research_nodes_conn))
    return patient_case_mRNA_research_nodes, patient_case_mRNA_research_nodes_conn