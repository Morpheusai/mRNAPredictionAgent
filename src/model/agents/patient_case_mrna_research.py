import aiosqlite

from pydantic import BaseModel, Field
from langgraph.config import get_stream_writer
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph
from langchain_core.messages import SystemMessage, AIMessage
from langgraph.types import Command
from typing import Literal, Any

from config import CONFIG_YAML

from src.model.agents.tools import (
    NeoAntigenSelection
)
from src.utils.log import logger
from src.utils.pdf_generator import neo_md2pdf

from .core import get_model  # 相对导入
from .core.patient_case_mrna_prompts import (
    PatientCaseReportAnalysisPrompt,
    PatientCaseReportSummaryPrompt
)

DOWNLOADER_URL_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["markdown_download_url_prefix"]

# Define the state for the agent
class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.
    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """
    mhc_allele: str
    cdr3: str
    input_fsa_filepath: str
    patient_case_summary: str
    mrna_design_process_result: str

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
    input_fsa_filepath: str = Field(
        ...,
        description="病人上传的fsa文件路径",
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
                file_path = file.file_path
                file_desc = file.file_desc
                file_instructions = f"*上传文件名*: {file_name} \n" + \
                                    f"*上传的文件描述*: {file_desc} \n" + \
                                    f"*上传的文件路径*: {file_path} \n" + \
                                    f"*上传的文件内容*: {file_content} \n"
                patient_info += file_instructions
    system_prompt = PatientCaseReportAnalysisPrompt.format(
        patient_info = patient_info,
    )
    logger.info(f"patient analysis prompt: {system_prompt}")
    writer = get_stream_writer()
    
    model_runnable = wrap_model(
        model, 
        system_prompt, 
        structure_model = True, 
        structure_output = PatientCaseSummaryReport
    )
    #writer("### 正在综合评估当前病例数据📊，确定是否满足mRNA疫苗接种条件💉✅。\n```json\n")
    response = await model_runnable.ainvoke(state, config)
    #writer("\n```\n ### 根据病例分析📊，该患者符合mRNA疫苗治疗条件✅。我们将立即启动个性化mRNA疫苗设计💉🔬，请您耐心等候⏳，我们会尽快完成这项精准医疗方案✨。")
    # TODO, debug
    action = response.action
    logger.info(f"patient analysis llm response: {response}, {action}")
    if action == "NO":
        return Command(
            update = {
                "messages": AIMessage(content="当前病人不适合做mRNA研究")
            },
            goto = END
        )
    mhc_allele = response.mhc_allele
    cdr3 = response.cdr3
    input_fsa_filepath = response.input_fsa_filepath
    summary = response.summary

    # 返回结果
    return Command(
        update = {
            "mhc_allele": mhc_allele,
            "cdr3": cdr3,
            "input_fsa_filepath": input_fsa_filepath,
            "patient_case_summary": summary
        },
        goto = "mrna_design_node"
    )

async def mRNADesignNode(state: AgentState, config: RunnableConfig):
    
    input_fsa_filepath = state["input_fsa_filepath"]
    mhc_allele = state["mhc_allele"]
    cdr3 = state["cdr3"]

    logger.info(f"mRNADesignNode args: fsa filename: {input_fsa_filepath}, mhc_allele: {mhc_allele}, cdr3: {cdr3}")
    # 1. 通过state参数构建NeoAntigenResearch工具输入参数
    mrna_design_process_result= await NeoAntigenSelection.ainvoke(
        {
            "input_file": input_fsa_filepath,
            "mhc_allele": [mhc_allele],
            "cdr3_sequence": [cdr3]
        }
    )
    return Command(
        update = {
            "mrna_design_process_result": mrna_design_process_result
        },
        goto = "patient_case_report"
    )

async def PatientCaseReportNode(state: AgentState, config: RunnableConfig):
    logger.info(f"patient case report node")
    mrna_design_process_result = state["mrna_design_process_result"]
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
                file_path = file.file_path
                file_desc = file.file_desc
                file_instructions = f"*上传文件名*: {file_name} \n" + \
                                    f"*上传的文件描述*: {file_desc} \n" + \
                                    f"*上传的文件路径*: {file_path} \n" + \
                                    f"*上传的文件内容*: {file_content} \n"
                patient_info += file_instructions
    logger.info(f"patient case report node, pi: {patient_info}")
    human_input = PatientCaseReportSummaryPrompt.format(
        patient_info = patient_info,
        process_info = mrna_design_process_result
    )
    messages = [
        HumanMessage(content=human_input),
    ]
    logger.info(f"patient case report prompt: {messages}")
    response = await model.ainvoke(messages)
    logger.info(f"patient case report response: {response}")
    writer = get_stream_writer()
    writer("\n#### 📝 正在进行病例报告PDF生成，💾 以提供下载\n")
    pdf_minio_path = neo_md2pdf(response.content)
    pdf_download_url = DOWNLOADER_URL_PREFIX + pdf_minio_path
    writer(f"\n🏥 已完成病例报告PDF生成，📥 请下载: [个性化mRNA疫苗设计-病例报告]({pdf_download_url}) \n")
    return Command(
        goto = END
    )

# Define the graph
PatientCaseMrnaAgent = StateGraph(AgentState)
PatientCaseMrnaAgent.add_node("patient_case_analysis", PatientCaseAnalysisNode)
PatientCaseMrnaAgent.add_node("mrna_design_node", mRNADesignNode)
PatientCaseMrnaAgent.add_node("patient_case_report", PatientCaseReportNode)

PatientCaseMrnaAgent.set_entry_point("patient_case_analysis")
PatientCaseMrnaAgent.add_edge("patient_case_analysis", "mrna_design_node")
PatientCaseMrnaAgent.add_edge("mrna_design_node", "patient_case_report")
PatientCaseMrnaAgent.add_edge("patient_case_report", END)

async def compile_patient_case_mRNA_research():
    patient_case_mRNA_research_nodes_conn = await aiosqlite.connect("checkpoints.sqlite")
    patient_case_mRNA_research_nodes = PatientCaseMrnaAgent.compile(checkpointer=AsyncSqliteSaver(patient_case_mRNA_research_nodes_conn))
    return patient_case_mRNA_research_nodes, patient_case_mRNA_research_nodes_conn
