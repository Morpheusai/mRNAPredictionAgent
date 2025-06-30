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

from src.utils.pdf_generator import neo_md2pdf
from src.utils.valid_fasta import validate_minio_fasta

from .prompt.neoantigen_report_template import PRIDICT_PATIENT_REPORT_ONE

DOWNLOADER_URL_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["markdown_download_url_prefix"]
MINIO_BUCKET = CONFIG_YAML["MINIO"]["molly_bucket"]

# Define the state for the agent
class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.
    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """
    mhc_allele: Optional[str]
    cdr3: Optional[List[str]] 
    input_fsa_filepath: Optional[str]
    mode: int #0-user, 1-demo
    neoantigen_message: Optional[List[str]] 
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
    try:
        file_path = config["configurable"].get("file_path", None)
        mhc_allele = config["configurable"].get("mhc_allele", None)
        cdr3 = config["configurable"].get("cdr3", None)
        tool_parameters = config["configurable"].get("tool_parameters", None)
        patient_id = config["configurable"].get("patient_id", None)
        predict_id = config["configurable"].get("predict_id", None)

        # 处理文件列表
        WRITER = get_stream_writer()
        if mhc_allele == None:
            STEP1_DESC2 = f"""
        \n ### ⚠️未能在病例中发现病人的HLA分型，请您在病历中提供病人的HLA分型
        """
            WRITER(STEP1_DESC2)
            return Command(goto=END)
        elif file_path == None:
            STEP1_DESC3 = f"""
        \n ### ⚠️未检测到您发送的fasta文件，请仔细检查您的肽段文件是否符合国际标准的fasta文件格式要求
        """
            WRITER(STEP1_DESC3)
            return Command(goto=END)
        elif (is_valid := validate_minio_fasta(file_path)) and not is_valid[0]:
            STEP1_DESC4 = f"""
        \n ### ⚠️请您仔细核对您上传的fasta文件是否符合格式要求，我们为您检测到的是:{is_valid[1]}
        """
            WRITER(STEP1_DESC4)
            return Command(goto=END)
        else:    
            WRITER("\n关键信息分析完毕，我们即将开始Neoantigen筛选过程⏳，我们会尽快完成这项精准医疗方案✨。\n")
            # 1. 通过state参数构建NeoantigenResearch工具输入参数
            neoantigen_message = await NeoantigenSelection.ainvoke(
                {
                    "input_file": file_path,
                    "mhc_allele": mhc_allele,
                    "cdr3_sequence": cdr3 if cdr3 is not None else cdr3,
                    "tool_parameters": tool_parameters,
                    "patient_id": patient_id,
                    "predict_id": predict_id,
                }
            )
            
            if not isinstance(neoantigen_message, list) or len(neoantigen_message) < 9:
                WRITER("\n⚠️ Neo-antigen筛选过程出现异常，请检查输入数据。\n")
                return Command(goto=END)
                
            return Command(
                update={
                    "mhc_allele": mhc_allele,
                    "cdr3": cdr3,
                    "input_fsa_filepath": file_path,
                    "neoantigen_message": neoantigen_message
                },
                goto="patient_case_report"
            )
    except Exception as e:
        WRITER(f"\n⚠️ 处理过程中出现错误: {str(e)}\n")
        return Command(goto=END)

async def PatientCaseReportNode(state: AgentState, config: RunnableConfig):
    try:
        writer = get_stream_writer()
        writer('\n')
        writer("\n ✅ 肽段数据分析完成，结合筛选过程生成报告...\n")

        neoantigen_array = state.get("neoantigen_message", [])
        if not isinstance(neoantigen_array, list) or len(neoantigen_array) < 9:
            writer("\n⚠️ 无法生成报告：数据格式不正确\n")
            return Command(goto=END)

        report_data = {
            'cleavage_count': neoantigen_array[0],
            'cleavage_link': f"[肽段切割]({DOWNLOADER_URL_PREFIX}{neoantigen_array[1]})" if neoantigen_array[1].startswith("minio://") else f"{neoantigen_array[1]}",
            'tap_count': neoantigen_array[2],
            'tap_link': f"[TAP 转运预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[3]})" if neoantigen_array[3].startswith("minio://") else f"{neoantigen_array[3]}",
            'affinity_count': neoantigen_array[4],
            'affinity_link': f"[亲和力预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[5]})" if neoantigen_array[5].startswith("minio://") else f"{neoantigen_array[5]}",
            'immunogenicity_count': neoantigen_array[6],
            'immunogenicity_link': f"[免疫原性预测]({DOWNLOADER_URL_PREFIX}{neoantigen_array[7]})" if neoantigen_array[7].startswith("minio://") else f"{neoantigen_array[7]}",
            'bigmhc_im_content': neoantigen_array[8],
        }

        patient_report_md = PRIDICT_PATIENT_REPORT_ONE.format(**report_data)
        pdf_download_link = neo_md2pdf(patient_report_md)
        writer("📄 完整分析细节、候选肽段列表与评分均已整理至报告中，可点击查看：")
        fdtime = datetime.now().strftime('%Y-%m-%d') 
        writer("#NEO_RESPONSE#")
        writer(f"👉 📥 下载报告：[Neoantigen筛选报告-{fdtime}]({pdf_download_link})")
        writer("#NEO_RESPONSE#\n")
        return Command(goto=END)
    except Exception as e:
        writer(f"\n⚠️ 生成报告时出现错误: {str(e)}\n")
        return Command(goto=END)

# 修改图结构
PredictNeoantigenSelectAgent = StateGraph(AgentState)
PredictNeoantigenSelectAgent.add_node("neoantigen_select_node", NeoantigenSelectNode)
PredictNeoantigenSelectAgent.add_node("patient_case_report", PatientCaseReportNode)

# 设置入口和条件边
PredictNeoantigenSelectAgent.set_entry_point("neoantigen_select_node")
PredictNeoantigenSelectAgent.add_edge("patient_case_report", END)

predict_neo_antigen_research = PredictNeoantigenSelectAgent.compile(
    checkpointer=MemorySaver(), 
    store=InMemoryStore()
)