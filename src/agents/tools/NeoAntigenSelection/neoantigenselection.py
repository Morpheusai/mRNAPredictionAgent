import asyncio
import json
import os
import uuid

from dotenv import load_dotenv
from minio.error import S3Error
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langchain_core.runnables import RunnableSerializable,RunnableLambda
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from pathlib import Path
import pandas as pd
from typing import List, Dict, Optional, AsyncIterator,Any

from config import CONFIG_YAML
from src.agents.tools.parameters import ToolParameters
from src.agents.tools.utils.step1_protein_cleavage import step1_protein_cleavage
from src.agents.tools.utils.step2_pmhc_binding_affinity import step2_pmhc_binding_affinity
from src.agents.tools.utils.step3_pmhc_immunogenicity import step3_pmhc_immunogenicity
from src.agents.tools.utils.step4_pmhc_tcr_interaction import step4_pmhc_tcr_interaction
from src.agents.tools.utils.step6_tap_transportation_prediction import step6_tap_transportation_prediction
from src.utils.minio_utils import upload_file_to_minio,download_from_minio_uri
from src.utils.ai_message_api import send_ai_message_to_server

load_dotenv()
# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MOLLY_BUCKET = MINIO_CONFIG["molly_bucket"]

NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
RNAFOLD_ENERGY_THRESHOLD = NEOANTIGEN_CONFIG["rnafold_energy_threshold"]
OUTPUT_TMP = CONFIG_YAML["TOOL"]["RNAFOLD"]["output_tmp_dir"]

async def wrap_summary_llm_model_async_stream(
    model: BaseChatModel, 
    system_prompt: str
) -> RunnableSerializable[Dict[str, Any], AsyncIterator[AIMessage]]:
    """包装模型，使其接受 `{"user_input": "..."}` 并返回流式 AI 响应"""
    
    async def stream_response(inputs: Dict[str, Any]) -> AsyncIterator[AIMessage]:
        # 构造消息：系统提示 + 用户输入
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=inputs["user_input"])
        ]
        
        # 流式调用模型
        async for chunk in model.astream(messages):
            yield chunk
    
    return RunnableLambda(stream_response)

def filter_rnafold(input_file_path: str, rnafold_energy_threshold: float) -> tuple[str, str]:
    """
    从MinIO下载RNAFold结果，过滤MFE结构，并上传到molly桶
    
    Args:
        input_file_path (str): MinIO路径，格式如 "minio://rnafold-results/54656457_RNAFold_results.xlsx"
        rnafold_energy_threshold (float): 自由能过滤阈值
    
    Returns:
        str: 新文件的MinIO路径（如 "minio://molly/filtered_54656457_RNAFold_results.xlsx"）
    """
    try:
        # 1. 解析MinIO路径
        if not input_file_path.startswith("minio://"):
            raise ValueError("Input path must start with 'minio://'")
        
        path_without_prefix = input_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        
        # 2. 下载文件到临时本地路径
        local_temp_path = f"{OUTPUT_TMP}/{uuid.uuid4().hex}.xlsx"
        local_temp_path=download_from_minio_uri(input_file_path,local_temp_path)
        # 3. 读取Excel并过滤MFE结构
        df = pd.read_excel(local_temp_path)
        
        # 提取自由能值（从"MFE结构"列）
        df["MFE_energy"] = df["MFE结构"].str.extract(r'\((-?\d+\.\d+)\)').astype(float)
        filtered_df = df[df["MFE_energy"] <= rnafold_energy_threshold]

        # 4. 生成Markdown格式字符串
        markdown_str = filtered_df.to_markdown(index=False)        
        
        # 5. 保存过滤结果到新文件
        filtered_local_path = f"{OUTPUT_TMP}/filtered_{Path(object_name).name}"
        filtered_df.to_excel(filtered_local_path, index=False)
        
        # 6. 上传到molly桶
        random_id = uuid.uuid4().hex
        new_object_name = f"{random_id}_filter_RNAFold_results.xlsx"

        mimio_path=upload_file_to_minio(filtered_local_path,MOLLY_BUCKET,new_object_name)
        # 6. 清理临时文件
        Path(local_temp_path).unlink(missing_ok=True)
        Path(filtered_local_path).unlink(missing_ok=True)        
        return markdown_str, mimio_path
    
    except S3Error as e:
        raise Exception(f"MinIO操作失败: {e}")
    except Exception as e:
        raise Exception(f"处理失败: {e}")

def normalize_hla_alleles(allele_str):
    """
    标准化 HLA 等位基因名称。
    输入: 字符串，多个等位基因用逗号分隔，如 "A0201,HLA-A02:01,B*07:02"
    输出: 标准化后的等位基因字符串，如 "HLA-A02:01,HLA-B07:02"
    """
    # 将输入字符串按逗号分割成列表
    allele_list = [a.strip() for a in allele_str.split(',') if a.strip()]
    
    print(allele_list)
    normalized = []
    for allele in allele_list:
        # 去除所有空格和可能的*
        allele = allele.replace(" ", "").replace("*", "")
        
        # 处理没有HLA前缀的情况（如A0201或A02:01）
        if not allele.startswith("HLA-"):
            # 检查是否以A/B/C开头，后面跟着数字（可能没有冒号）
            if allele[0] in ["A", "B", "C"]:
                # 处理A0201（无冒号）的情况
                if ":" not in allele:
                    # 确保格式是A0201 -> A02:01（假设前两位是基因，后两位是编号）
                    allele = f"{allele[:1]}{allele[1:3]}:{allele[3:]}"
                # 添加HLA-前缀
                allele = "HLA-" + allele
            else:
                # 其他格式可能需要额外处理
                pass
        
        # 确保冒号后的编号是两位（如HLA-A02:01而不是HLA-A02:1）
        if ":" in allele:
            parts = allele.split(":")
            if len(parts) == 2:
                # 补全冒号后的数字为两位
                parts[1] = parts[1].zfill(2)
                allele = ":".join(parts)
        
        normalized.append(allele)
    
    # 将标准化后的列表用逗号连接成字符串返回
    return ','.join(normalized)

async def run_neoantigenselection(
    input_file: str,
    mhc_allele: Optional[str] = None,
    cdr3_sequence: Optional[List[str]] = None,
    tool_parameters: Optional[ToolParameters] = None,
    patient_id: Optional[int] = None, 
    predict_id: Optional[int] = None,
    conversation_id: Optional[int] = None
) -> str:
    """
    运行新抗原筛选流程
    
    Args:
        input_file: 输入文件路径
        mhc_allele: MHC等位基因列表
        cdr3_sequence: CDR3序列列表
        patient_id: 病人id（int类型）
        predict_id: 预测表id
    Returns:
        str: JSON格式的结果字符串
    """
    # 新增：如果tool_parameters为None，自动用默认值创建
    if tool_parameters is None:
        tool_parameters = ToolParameters()
    # 初始化变量
    neoantigen_message = ["--"] * 9
    cleavage_m=0
    tap_m=0
    pmhc_binding_m=0
    pmhc_immunogenicity_m=0
    tcr_m=0

    mhc_allele=normalize_hla_alleles(mhc_allele)
    try:
        # 第一步：蛋白切割位点预测
        netchop_parameters = tool_parameters.get_netchop_parameters()
        netchop_parameters.input_filename = input_file
        cleavage_result_file_path, netchop_final_result_str,cleavage_m = await step1_protein_cleavage(
            netchop_parameters, 
            neoantigen_message,
            patient_id,
            predict_id,
            conversation_id,
        )
        neoantigen_message[0] = f"{cleavage_m}/{cleavage_m}"
        neoantigen_message[1] = cleavage_result_file_path

        # 第二步：TAP转运预测
        netctlpan_parameters = tool_parameters.get_netctlpan_parameters()
        # netctlpan_parameters.input_filename = cleavage_result_file_path
        netctlpan_parameters.input_filename = input_file
        netctlpan_parameters.mhc_allele = mhc_allele
        netctlpan_file_path, netctlpan_fasta_str, tap_m,netctlpan_tool_url = await step6_tap_transportation_prediction(
            netctlpan_parameters,
            neoantigen_message,
            cleavage_m,
            patient_id,
            predict_id,
            conversation_id,
        )
        neoantigen_message[2]=f"{tap_m}/{cleavage_m}"
        neoantigen_message[3]=netctlpan_tool_url

        # 第三步：pMHC结合亲和力预测
        netmhcpan_parameters = tool_parameters.get_netmhcpan_parameters()
        netmhcpan_parameters.input_filename = netctlpan_file_path
        netmhcpan_parameters.mhc_allele = mhc_allele
        netmhcpan_result_file_path, mhcpan_count = await step2_pmhc_binding_affinity(
            netmhcpan_parameters,
            neoantigen_message,
            tap_m,
            patient_id,
            predict_id,
            conversation_id,
        )

        # 第四步：pMHC免疫原性预测
        bigmhc_parameters = tool_parameters.get_bigmhc_im_parameters()
        bigmhc_parameters.input_filename = netmhcpan_result_file_path 
        bigmhc_im_result_file_path, bigmhc_im_fasta_str,pmhc_immunogenicity_m, bigmhc_im_tool_url, bigmhc_im_content= await step3_pmhc_immunogenicity(
            bigmhc_parameters, 
            neoantigen_message,
            pmhc_binding_m,
            patient_id,
            predict_id,
            conversation_id,
        )
        neoantigen_message[6]=f"{pmhc_immunogenicity_m}/{mhcpan_count}"
        neoantigen_message[7]=bigmhc_im_tool_url
        neoantigen_message[8]=bigmhc_im_content

        STEP1_DESC2 = f"""
\n## 📄 综合结论：
\n✅ 本次筛选流程中，系统最终识别出**{pmhc_immunogenicity_m}条在抗原递呈、免疫激活与T细胞识别多个维度均表现优异的个体化 neoantigen 候选肽段**，建议作为后续疫苗设计重点靶点。
    """
        send_ai_message_to_server(conversation_id, STEP1_DESC2)

#目前不需要cdr3序列的预测
        # # 第五步：pMHC-TCR相互作用预测
        # mrna_input_file_path,tcr_m,tcr_content,pmtnet_result_tool_url= await step4_pmhc_tcr_interaction(
        #     bigmhc_im_result_file_path, 
        #     cdr3_sequence, 
        #     writer, 
        #     neoantigen_message,
        #     pmhc_immunogenicity_m
        # )

        # if cdr3_sequence is not None:
        #     neoantigen_message[10] = f"{tcr_m}/{pmhc_immunogenicity_m * len(cdr3_sequence)}"
        #     neoantigen_message[11]=pmtnet_result_tool_url
        #     neoantigen_message[12]=tcr_content
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"流程执行失败，完整异常栈:\n{error_traceback}")
        print(f"流程执行失败: {str(e)}")
        # 写入日志
        try:
            from src.utils.log import logger
            logger.error(f"流程执行失败，完整异常栈:\n{error_traceback}")
            logger.error(f"流程执行失败: {str(e)}")
        except Exception:
            pass
    finally:
        # 返回最终结果
        return neoantigen_message

@tool
async def NeoantigenSelection(
    input_file: str,
    mhc_allele: Optional[str] = None, 
    cdr3_sequence: Optional[List[str]] = None,
    tool_parameters: Optional[ToolParameters] = None,
    patient_id: Optional[int] = None, 
    predict_id: Optional[int] = None,
    conversation_id: Optional[int] = None
) -> str:
    """                                    
    NeoantigenSelection是基于用户输入的患者信息，结合已有的工具库，完成个体化neo-antigen筛选。
    Args:                                  
        input_file (str): 输入的肽段序例fasta文件路径           
        mhc_allele (Optional[List[str]]): MHC比对的等位基因。
        cdr3_sequence (Optional[List[str]]): cdr3序列。
        tool_parameters (Optional[Dict[str, Any]]): 工具参数
        patient_id (Optional[int]): 病人id
        predict_id (Optional[int]): 预测表id
    Returns:                               
        str: 返回高结合亲和力的肽段序例信息                                                                                                                           
    """
    # neoantigen_message = ["--"] * 9
    try:
        result = await run_neoantigenselection(
            input_file, 
            mhc_allele, 
            cdr3_sequence,
            tool_parameters,
            patient_id,
            predict_id,
            conversation_id
        )
        return result
    except Exception as e:
        result = {
            "type": "text",
            "content": f"调用NeoantigenSelection工具失败: {e}"
        }
        return json.dumps(result, ensure_ascii=False)
    
if __name__ == "__main__":
    input_file = "minio://molly/ab58067f-162f-49af-9d42-a61c30d227df_test_netchop.fsa"
    
    # 最佳调用方式
    tool_result = NeoantigenSelection.invoke({
        "input_file": input_file,
        "mhc_allele": ["HLA-A02:01"],})