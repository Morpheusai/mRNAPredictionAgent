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
from src.utils.pdf_generator import neo_md2pdf
from src.utils.valid_fasta import validate_minio_fasta

from .prompt.neoantigen_research_prompt import (
    PLATFORM_INTRO,
    NEOANTIGEN_CHAT_PROMPT,
)

from .prompt.neoantigen_report_template import PRIDICT_PATIENT_REPORT_ONE

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


async def NeoantigenSelectNode(state: AgentState, config: RunnableConfig):

    file_path = config["configurable"].get("file_path", None)
    mhc_allele = config["configurable"].get("mhc_allele", None)
    cdr3 = config["configurable"].get("cdr3", None)
    # 处理文件列表
    WRITER = get_stream_writer()
    if mhc_allele ==None:
        # INSERT_SPACER=""
        STEP1_DESC2 = f"""
    \n ### ⚠️未能在病例中发现病人的HLA分型，请您在病历中提供病人的HLA分型
    """
        # WRITER(INSERT_SPACER)
        WRITER(STEP1_DESC2)
    elif file_path ==None:
        # INSERT_SPACER=""
        STEP1_DESC3 = f"""
    \n ### ⚠️未检测到您发送的fasta文件，请仔细检查您的肽段文件是否符合国际标准的fasta文件格式要求
    """
        # WRITER(INSERT_SPACER)
        WRITER(STEP1_DESC3)
        return Command(
            goto = END
        )
    elif (is_valid := validate_minio_fasta(file_path)) and not is_valid[0]:
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
                "input_file": file_path,
                "mhc_allele": mhc_allele,
                "cdr3_sequence": cdr3 if cdr3 is not None else cdr3
            }
        )
        return Command(
            update = {
                "mhc_allele": mhc_allele,
                "cdr3": cdr3,
                "input_fsa_filepath": file_path,
                "neoantigen_message": neoantigen_message

            },
            goto = "patient_case_report"
        )

async def PatientCaseReportNode(state: AgentState, config: RunnableConfig):

    writer = get_stream_writer()
#writer("\n```\n ✅ 病例数据分析完成，结合筛选过程生成病例报告...\n")
    writer('\n')
    writer("\n ✅ 肽段数据分析完成，结合筛选过程生成报告...\n")


    neoantigen_message_str = state.get("neoantigen_message", "")
    neoantigen_array = neoantigen_message_str.split("#NEO#") if neoantigen_message_str else []
    report_data = {
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
    patient_report_md = PRIDICT_PATIENT_REPORT_ONE.format(**report_data)
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
PredictNeoantigenSelectAgent = StateGraph(AgentState)
PredictNeoantigenSelectAgent.add_node("neoantigen_select_node", NeoantigenSelectNode)
PredictNeoantigenSelectAgent.add_node("patient_case_report", PatientCaseReportNode)

# 设置入口和条件边
PredictNeoantigenSelectAgent.set_entry_point("neoantigen_select_node")
PredictNeoantigenSelectAgent.add_edge("patient_case_report", END)

predict_neo_antigen_research = PredictNeoantigenSelectAgent.compile(
    checkpointer = MemorySaver(), 
    store = InMemoryStore()
)
