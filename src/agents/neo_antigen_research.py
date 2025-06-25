from datetime import datetime
from pydantic import BaseModel, Field
from langgraph.config import get_stream_writer
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langchain_core.messages import SystemMessage, AIMessage
from langgraph.types import Command
from typing import Any, Optional,List

from config import CONFIG_YAML

from src.agents.tools import (
    NeoantigenSelection
)
from src.core import get_model, settings
from src.utils.log import logger
from src.utils.pdf_generator import neo_md2pdf
from src.utils.valid_fasta import validate_minio_fasta

from .prompt.neoantigen_research_prompt import (
    NEOATIGIGEN_ROUTE_PROMPT,
    PLATFORM_INTRO,
    NEOANTIGEN_CHAT_PROMPT,
    PATIENT_KEYINFO_EXTRACT_PROMPT,
    PATIENT_CASE_ANALYSIS_PROMPT,
)
from .prompt.neoantigen_report_template import PATIENT_REPORT_ONE

DOWNLOADER_URL_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["markdown_download_url_prefix"]
MINIO_BUCKET = CONFIG_YAML["MINIO"]["molly_bucket"]

# Define the state for the agent
class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.
    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """
    mhc_allele: Optional[List[str]]
    cdr3: Optional[List[str]] 
    input_fsa_filepath: Optional[str]
    mode: int #0-user, 1-demo
    neoantigen_message: str
    patient_neoantigen_report: str

# Data model
class PatientCaseSummaryReport(BaseModel):
    """病例数据分析后的总结输出结果."""
    mhc_allele: Optional[List[str]] = Field(
        None,
        description="病例中测结果中检测到的MHC allele",
    )
    cdr3: Optional[List[str]] = Field(
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
    model = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
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
    model = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
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
    mode = 1
    if messages and isinstance(messages[-1], AIMessage):
        last_msg = messages[-1]
        if "用户数据处理" in last_msg.content:
            mode = 0
    model = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    #添加文件到system token里面
    file_list = config["configurable"].get("file_list", None)
    # 处理文件列表
    WRITER = get_stream_writer()
    patient_info = ""
    file_used = 0
    opposite_file_used = 0
    if file_list:
        for conversation_file in file_list:
            for file in conversation_file.files:
                file_name = file.file_name
                file_content = file.file_content
                file_path = file.file_path
                file_desc = file.file_desc
                file_origin = file.file_origin
                # 判断文件来源, 对应不同的模式
                if mode != file_origin:
                    opposite_file_used += 1
                    continue
                file_instructions = f"*上传文件名*: {file_name} \n" + \
                                    f"*上传的文件描述*: {file_desc} \n" + \
                                    f"*上传的文件路径*: {file_path} \n" + \
                                    f"*上传的文件内容*: {file_content} \n" + \
                                    f"*上传的文件来源（0表示用户上传文件，1表示系统上传文件）*: {file_origin} \n"
                patient_info += file_instructions
                file_used += 1
    FILE_CHECK_INFO = ""
    if len(patient_info) == 0:
        if mode == 1:
            if opposite_file_used == 0:
                FILE_CHECK_INFO = \
    """
        \n📌 请您查看并确认使用引导提示中我们为您准备的 
           ▸ 1️⃣  模拟病历[PancreaticCase.txt]
           ▸ 2️⃣  突变序列示例数据[PancreaticSeq.fsa]
        确认使用文件后，请告知我，即刻可以开始**示例体验流程**\n
        """
                WRITER(FILE_CHECK_INFO)
            else :    
                FILE_CHECK_INFO = f"""
        \n⚠️ **检测到您上传自己的{opposite_file_used}个数据文件** ⚠️\n
        \n📌 请您查看并确认使用引导提示中我们为您准备的 
          ▸ 1️⃣  模拟病历[PancreaticCase.txt]
          ▸ 2️⃣  突变序列示例数据[PancreaticSeq.fsa]
        确认使用文件后，请告知我，即刻可以开始**示例体验流程**\n
        """
                WRITER(FILE_CHECK_INFO)
        else:
            if opposite_file_used == 0:
                FILE_CHECK_INFO = \
    """
\n📌 请您上传自己的数据文件，文件需要满足以下要求：
▸ 1️⃣  患者病例信息（TXT格式）
　　▸  🏥 包含：患者基本信息、诊断、治疗背景、HLA分型、TCR序列等
▸ 2️⃣  突变肽段序列文件（FASTA格式）
　　▸  🧬 示例文件名：`mutation_peptides.fasta` \n
"""
                WRITER(FILE_CHECK_INFO)
            else :    
                FILE_CHECK_INFO = f"""
\n⚠️ **检测到您上传了{opposite_file_used}个案例文件** ⚠️\n
\n📌 请您上传自己的数据文件，文件需要满足以下要求：
▸ 1️⃣  患者病例信息（TXT格式）
　　▸  🏥 包含：患者基本信息、诊断、治疗背景、HLA分型、TCR序列等
▸ 2️⃣  突变肽段序列文件（FASTA格式）
　　▸  🧬 示例文件名：`mutation_peptides.fasta` \n
"""
                WRITER(FILE_CHECK_INFO)
        return Command(
            update = {
                "messages": [
                    AIMessage(content = FILE_CHECK_INFO)
                ]
            },
            goto = END
        )
    elif file_used == 1:
        if mode == 1:
            if opposite_file_used == 0:
                FILE_CHECK_INFO = \
    """
🔍 系统检测到当前情况：
 ▸  ✅ 使用了1个示例文件  

📌 请确认使用我们为您准备的完整示例文件包：
 ▸ 🏥 模拟病历 [PancreaticCase.txt]  
 ▸ 🧬 突变序列数据 [PancreaticSeq.fsa]

💬 确认两个文件都已就绪后，请告诉我，我们将立即开始✨示例预测流程✨
"""
                WRITER(FILE_CHECK_INFO)
            else :    
                FILE_CHECK_INFO = f"""
🔍 系统检测到当前情况：
 ▸  ✅ 使用了1个示例文件  
 ▸  ⚠️ 另有{opposite_file_used}个非示例文件

📌 请确认使用我们为您准备的完整示例文件包：
 ▸ 🏥 模拟病历 [PancreaticCase.txt]  
 ▸ 🧬 突变序列数据 [PancreaticSeq.fsa]

💬 确认两个文件都已就绪后，请告诉我，我们将立即开始✨示例预测流程✨
"""

                WRITER(FILE_CHECK_INFO)

        else:
            if opposite_file_used == 0:
                FILE_CHECK_INFO = f"""
📊 系统检测结果：
 ▸  ✅ 已识别到1个您上传的文件
 ▸  📂 另有{opposite_file_used}个用户案例文件
📌 请补充上传以下完整资料：
 ▸   1️⃣ 【患者医疗档案】🏥 (TXT格式)
　　▸  包含患者基本信息、诊断、治疗背景、HLA分型、TCR序列等
 ▸   2️⃣ 【突变肽段序列】🧬 (FASTA格式)
　　▸  📝 文件名示例：mutation_peptides.fasta
　　▸  ✅ 请确保符合FASTA格式规范
💡 当两份文件都准备好后，请告知我立即开始分析！
"""
                WRITER(FILE_CHECK_INFO)
            else :    
                FILE_CHECK_INFO = f"""
📊 系统检测结果：
 ▸  ✅ 已识别到1个您上传的文件
 ▸  📂 另有{opposite_file_used}个用户案例文件
📌 请补充上传以下完整资料：
 ▸  1️⃣ 【患者医疗档案】🏥 (TXT格式)
　　▸  包含患者基本信息、诊断、治疗背景、HLA分型、TCR序列等
 ▸  2️⃣ 【突变肽段序列】🧬 (FASTA格式)
　　▸  📝 文件名示例：mutation_peptides.fasta
　　▸  ✅ 请确保符合FASTA格式规范
💡 当两份文件都准备好后，请告知我立即开始分析！
"""
                WRITER(FILE_CHECK_INFO)

        return Command(
            update = {
                "messages": [
                    AIMessage(content = FILE_CHECK_INFO)
                ]
            },
            goto = END
        )
    STEP1_DESC1 = f"""
## 🧪 正在体验示例分析流程…
我们已加载平台内置示例数据（张先生，胰腺导管腺癌）并启动个体化 Neoantigen 筛选流程。先提取筛选过程中的关键信息：

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
    WRITER("\n```")
    # TODO, debug
    logger.info(f"patient key info llm response: {response}")
    mhc_allele = response.mhc_allele
    cdr3 = response.cdr3
    input_fsa_filepath = response.input_fsa_filepath

    logger.info(f"mRNADesignNode args: fsa filename: {input_fsa_filepath}, mhc_allele: {mhc_allele}, cdr3: {cdr3}")
    if mhc_allele ==None:
        # INSERT_SPACER=""
        STEP1_DESC2 = f"""
    \n ### ⚠️未能在病例中发现病人的HLA分型，请您在病历中提供病人的HLA分型
    """
        # WRITER(INSERT_SPACER)
        WRITER(STEP1_DESC2)
    elif input_fsa_filepath ==None:
        # INSERT_SPACER=""
        STEP1_DESC3 = f"""
    \n ### ⚠️未检测到您发送的fasta文件，请仔细检查您的肽段文件是否符合国际标准的fasta文件格式要求
    """
        # WRITER(INSERT_SPACER)
        WRITER(STEP1_DESC3)
        return Command(
            goto = END
        )
    elif (is_valid := validate_minio_fasta(input_fsa_filepath)) and not is_valid[0]:
        STEP1_DESC4 = f"""
    \n ### ⚠️请您仔细核对您上传的fasta文件是否符合格式要求，我们为您检测到的是:{is_valid[1]}
    """
        WRITER(STEP1_DESC4)
        return Command(
            goto = END
        )
    else:    
        WRITER("\n关键信息分析完毕，我们即将开始Neoantigen筛选过程⏳，我们会尽快完成这项精准医疗方案✨。\n")
        # 1. 通过state参数构建NeoantigenResearch工具输入参数
        neoantigen_message= await NeoantigenSelection.ainvoke(
            {
                "input_file": input_fsa_filepath,
                "mhc_allele": mhc_allele,
                "cdr3_sequence": cdr3 if cdr3 is not None else cdr3
            }
        )
        return Command(
            update = {
                "mhc_allele": mhc_allele,
                "cdr3": cdr3,
                "input_fsa_filepath": input_fsa_filepath,
                "mode": mode,
                "neoantigen_message": neoantigen_message

            },
            goto = "patient_case_report"
        )

async def PatientCaseReportNode(state: AgentState, config: RunnableConfig):
    model = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    file_list = config["configurable"].get("file_list", None)
    mode = state.get("mode", 1)
    cdr3 = state.get("cdr3", None)
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
                file_origin = file.file_origin
                if mode != file_origin:
                    continue
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
#    WRITER("```json\n")
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
#writer("\n```\n ✅ 病例数据分析完成，结合筛选过程生成病例报告...\n")
    WRITER('\n')
    writer("\n ✅ 病例数据分析完成，结合筛选过程生成病例报告...\n")
    patient_case_analysis_summary = response.content

    neoantigen_message_str = state.get("neoantigen_message", "")
    neoantigen_array = neoantigen_message_str.split("#NEO#") if neoantigen_message_str else []
    report_data = {
        'patient_case_report': patient_case_analysis_summary,
        'cleavage_count':  neoantigen_array[0],
        'cleavage_link': f"[肽段切割]({DOWNLOADER_URL_PREFIX}{neoantigen_array[1]})" if neoantigen_array[1].startswith("minio://") else f"{neoantigen_array[1]}",
        'tap_count':  neoantigen_array[2],
        'tap_link': f"[TAP 转运预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[3]})" if neoantigen_array[3].startswith("minio://") else f"{neoantigen_array[3]}",
        'affinity_count':  neoantigen_array[4],
        'affinity_link': f"[亲和力预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[5]})" if neoantigen_array[5].startswith("minio://") else f"{neoantigen_array[5]}",
        # 'binding_count':  neoantigen_array[6],
        # 'binding_link': f"[抗原呈递预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[7]})" if neoantigen_array[7].startswith("minio://") else f"{neoantigen_array[7]}",
        'immunogenicity_count':  neoantigen_array[6],
        'immunogenicity_link': f"[免疫原性预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[7]})" if neoantigen_array[7].startswith("minio://") else f"{neoantigen_array[7]}",
        'bigmhc_im_content': neoantigen_array[8],
        # 'tcr_count':  neoantigen_array[10],
        # 'tcr_link':  f"[TCR 识别预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[11]})" if neoantigen_array[11].startswith("minio://") else f"{neoantigen_array[11]}",
        # 'tcr_content':  neoantigen_array[12] if cdr3 is not None else "\n在病人病例中未提供cdr3序列，不能得到最终的筛选结论"
    }
    patient_report_md = PATIENT_REPORT_ONE.format(**report_data)
    # if cdr3 is not None:
    #     patient_report_md = PATIENT_REPORT_ONE.format(**report_data)
    # else:
    #     patient_report_md = PATIENT_REPORT_TWO.format(**report_data)
    #输出为pdf，并提供下载link
    pdf_download_link = neo_md2pdf(patient_report_md)
    writer("📄 完整分析细节、候选肽段列表与评分均已整理至报告中，可点击查看：")
    fdtime = datetime.now().strftime('%Y-%m-%d') 
    writer("#NEO_RESPONSE#")
    writer(f"👉 📥 下载报告：[Neoantigen筛选报告-{fdtime}]({pdf_download_link})")
    writer("#NEO_RESPONSE#\n")
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
NeoantigenSelectAgent.add_edge("patient_case_report", END)

neo_antigen_research = NeoantigenSelectAgent.compile(
    checkpointer = MemorySaver(), 
    store = InMemoryStore()
)
