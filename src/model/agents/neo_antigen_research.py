import aiosqlite
import uuid

from datetime import datetime
from pydantic import BaseModel, Field
from langgraph.config import get_stream_writer
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, MessagesState, StateGraph
from langchain_core.messages import SystemMessage, AIMessage
from langgraph.types import Command
from typing import Literal, Any,Optional

from config import CONFIG_YAML

from src.model.agents.tools import (
    NeoantigenSelection
)
from src.utils.log import logger
from utils.minio_utils import upload_file_to_minio

from .core import get_model  # 相对导入
from .core.neoantigen_research_prompt import (
    NEOATIGIGEN_ROUTE_PROMPT,
    PLATFORM_INTRO,
    NEOANTIGEN_CHAT_PROMPT,
    PATIENT_KEYINFO_EXTRACT_PROMPT,
    PATIENT_CASE_ANALYSIS_PROMPT,
)
from .core.neoantigen_report_template import PATIENT_REPORT

DOWNLOADER_URL_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["markdown_download_url_prefix"]
MINIO_BUCKET = CONFIG_YAML["MINIO"]["molly_bucket"]

# Define the state for the agent
class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.
    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """
    mhc_allele: str
    cdr3: str
    input_fsa_filepath: str
    patient_case_summary: str
    # mrna_design_process_result: str
    patient_neoantigen_report: str
    neoantigen_message: str

# Data model
class PatientCaseSummaryReport(BaseModel):
    """病例数据分析后的总结输出结果."""
    mhc_allele: Optional[str] = Field(
        None,
        description="病例中测结果中检测到的MHC allele",
    )
    cdr3: Optional[str] = Field(
        None,
        description="病例中测结果中检测到的CDR3序列",
    )
    input_fsa_filepath: Optional[str] = Field(
        None,
        description="病人上传的fsa文件路径",
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

async def NeoantigenRouteNode(state: AgentState, config: RunnableConfig) -> AgentState:
    model = get_model(
        config["configurable"].get("model", None),
        config["configurable"].get("temperature", None),
        config["configurable"].get("max_tokens", None),
        config["configurable"].get("base_url", None),
        config["configurable"].get("frequency_penalty", None),
        stream_mode = False,  # 不使用流式输出
    )
    system_prompt = NEOATIGIGEN_ROUTE_PROMPT
    logger.info(f"neoantigen route prompt: {system_prompt}")
    model_runnable = wrap_model(
        model, 
        system_prompt, 
        structure_model = False, 
    )
    response = await model_runnable.ainvoke(state, config)

    # 检查最后一条消息是否包含关键内容
    next_node = END
    if "了解平台" in response.content:
        next_node = "platform_intro"
    elif "示例体验" in response.content:
        next_node = "neoantigen_select_node"
    elif "用户数据处理" in response.content:
        next_node = "neoantigen_select_node"
    else:
        next_node = "neoantigen_select_chat"

    WRITER = get_stream_writer()
    WRITER('\n')
    return Command(
        update = {
            "messages": [response]
        },
        goto = next_node
    )

async def PlatformIntroNode(state: AgentState, config: RunnableConfig):
    logger.info("Into Platform introduction")
    WRITER = get_stream_writer()
    WRITER('\n')
    for pi in PLATFORM_INTRO.split("\n"):
        WRITER(f"{pi}\n")
    WRITER('\n')
    logger.info("Platform introduction end")
    return Command(
        goto = END
    )

async def NeoantigenSelectChat(state: AgentState, config: RunnableConfig):
    model = get_model(
        config["configurable"].get("model", None),
        config["configurable"].get("temperature", None),
        config["configurable"].get("max_tokens", None),
        config["configurable"].get("base_url", None),
        config["configurable"].get("frequency_penalty", None),
    )
    patient_neoantigen_report = state.get("patient_neoantigen_report", "")
    system_prompt = NEOANTIGEN_CHAT_PROMPT.format(
        prompt_intro = PLATFORM_INTRO,
        patient_neoantigen_report = patient_neoantigen_report
    )
    logger.info(f"neoantigen chat prompt: {system_prompt}")
    model_runnable = wrap_model(
        model, 
        system_prompt, 
    )
    response = await model_runnable.ainvoke(state, config)
    logger.info(f"neoantigen chat response: {response}")
    return Command(
        update = {
            "messages": [response]
        },
        goto = END
    )

async def NeoantigenSelectNode(state: AgentState, config: RunnableConfig):
    messages = state.get("messages", [])
    mode = "demo"
    if messages and isinstance(messages[-1], AIMessage):
        last_msg = messages[-1]
        if "用户数据处理" in last_msg.content:
            mode = "user"

    model = get_model(
        config["configurable"].get("model", None),
        config["configurable"].get("temperature", None),
        config["configurable"].get("max_tokens", None),
        config["configurable"].get("base_url", None),
        config["configurable"].get("frequency_penalty", None),
        stream_mode = False
    )
    #添加文件到system token里面
    file_list = config["configurable"].get("file_list", None)
    # 处理文件列表
    WRITER = get_stream_writer()
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
    else:
        if mode == "demo":
            WRITER("\n请使用平台提供的默认示例数据进行平台体验。\n")
        else:
            WRITER("\n请上传以下两类文件：\n"
                   "1. 患者病例信息（TXT）\n"
                   "   ◦ 包含患者基本信息、诊断、治疗背景、HLA分型、TCR序列等\n"
                   "2. 突变肽段序列文件（FASTA格式）\n"
                   "   ◦ 示例文件名：mutation_peptides.fasta\n")
        return Command(
            goto = END
        )
    STEP1_DESC1 = f"""
## 🧪 正在体验示例分析流程…
我们已加载平台内置示例数据（张先生，胰腺导管腺癌）并启动个体化 neoantigen 筛选流程。先提取筛选过程中的关键信息：

"""
    WRITER(STEP1_DESC1)
    WRITER("```json\n")
    system_prompt = PATIENT_KEYINFO_EXTRACT_PROMPT.format(
        patient_info = patient_info,
    )
    logger.info(f"patient key info extract prompt: {system_prompt}")
    model_runnable = wrap_model(
        model, 
        system_prompt, 
        structure_model = True, 
        structure_output = PatientCaseSummaryReport
    )
    response = await model_runnable.ainvoke(state, config)
    WRITER("\n```\n 关键信息分析完毕，我们即将开始Neoantigen筛选过程⏳，我们会尽快完成这项精准医疗方案✨。\n")
    # TODO, debug
    logger.info(f"patient key info llm response: {response}")
    mhc_allele = response.mhc_allele
    cdr3 = response.cdr3
    input_fsa_filepath = response.input_fsa_filepath

    logger.info(f"mRNADesignNode args: fsa filename: {input_fsa_filepath}, mhc_allele: {mhc_allele}, cdr3: {cdr3}")
    # 1. 通过state参数构建NeoantigenResearch工具输入参数
    neoantigen_message= await NeoantigenSelection.ainvoke(
        {
            "input_file": input_fsa_filepath,
            "mhc_allele": [mhc_allele],
            "cdr3_sequence": [cdr3]
        }
    )
    print(neoantigen_message)
    return Command(
        update = {
            "mhc_allele": mhc_allele,
            "cdr3": cdr3,
            "input_fsa_filepath": input_fsa_filepath,
            "neoantigen_message": neoantigen_message

        },
        goto = "patient_case_report"
    )

async def PatientCaseReportNode(state: AgentState, config: RunnableConfig):
    model = get_model(
        config["configurable"].get("model", None),
        config["configurable"].get("temperature", None),
        config["configurable"].get("max_tokens", None),
        config["configurable"].get("base_url", None),
        config["configurable"].get("frequency_penalty", None),
        stream_mode = False
    )
    #添加文件到system token里面
    file_list = config["configurable"].get("file_list", None)
    # 处理文件列表
    WRITER = get_stream_writer()
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

    STEP1_DESC1 = f"""
## 生成个性化neoantigen筛选报告
### 📝 病例数据分析
"""
    WRITER(STEP1_DESC1)
    WRITER("```json\n")
    system_prompt = PATIENT_CASE_ANALYSIS_PROMPT.format(
        patient_info = patient_info,
    )
    model_runnable = wrap_model(
        model, 
        system_prompt
    )
    logger.info(f"patient case analysis prompt: {system_prompt}")
    response = await model_runnable.ainvoke(state, config)
    writer = get_stream_writer()
    writer("\n```\n ✅ 病例数据分析完成，结合筛选过程生成病例报告...\n")
    patient_case_report = f"""
{response.content}
    """

    neoantigen_message_str = state.get("neoantigen_message", "")
    neoantigen_array = neoantigen_message_str.split("#NEO#") if neoantigen_message_str else []
    report_data = {
        'patient_case_report': patient_case_report,
        'cleavage_count':  neoantigen_array[0],
        'cleavage_link': f"[肽段切割]({DOWNLOADER_URL_PREFIX}{neoantigen_array[1]})",
        'tap_count':  neoantigen_array[2],
        'tap_link': f"[TAP 转运预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[3]})",
        'affinity_count':  neoantigen_array[4],
        'affinity_link': f"[亲和力预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[5]})",
        'binding_count':  neoantigen_array[6],
        'binding_link': f"[抗原呈递预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[7]})",
        'immunogenicity_count':  neoantigen_array[8],
        'immunogenicity_link': f"[免疫原性预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[9]})",
        'tcr_count':  neoantigen_array[10],
        'tcr_link':  f"[TCR 识别预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[11]})",
        'tcr_content':  neoantigen_array[12]
    }

    patient_report = PATIENT_REPORT.format(**report_data)
    

    # 输出到minio
    temp_report_file = f"/mnt/data/temp/neoantigen_report_{uuid.uuid4().hex}.md"
    with open(temp_report_file, "w") as fout:
        fout.write(patient_report)
    final_report_filepath = upload_file_to_minio(
        temp_report_file,
        MINIO_BUCKET
    )
    writer("📄 完整分析细节、候选肽段列表与评分均已整理至报告中，可点击查看：")
    fdtime = datetime.now().strftime('%Y-%m-%d') 
    writer(f"👉 📥 下载报告：[Neoantigen筛选报告-张先生-{fdtime}]({final_report_filepath})")
    return Command(
        goto = END
    )

# 修改图结构
NeoantigenSelectAgent = StateGraph(AgentState)
NeoantigenSelectAgent.add_node("neoantigen_route_node", NeoantigenRouteNode)
NeoantigenSelectAgent.add_node("platform_intro", PlatformIntroNode)
NeoantigenSelectAgent.add_node("neoantigen_select_node", NeoantigenSelectNode)
NeoantigenSelectAgent.add_node("neoantigen_select_chat", NeoantigenSelectChat)
NeoantigenSelectAgent.add_node("patient_case_report", PatientCaseReportNode)

# 设置入口和条件边
NeoantigenSelectAgent.set_entry_point("neoantigen_route_node")
NeoantigenSelectAgent.add_edge("neoantigen_select_node", "patient_case_report")
NeoantigenSelectAgent.add_edge("patient_case_report", END)

async def compile_neo_antigen_research():
    neo_antigen_research_conn = await aiosqlite.connect("checkpoints.sqlite")
    neo_antigen_research = NeoantigenSelectAgent.compile(checkpointer=AsyncSqliteSaver(neo_antigen_research_conn))
    return neo_antigen_research, neo_antigen_research_conn
