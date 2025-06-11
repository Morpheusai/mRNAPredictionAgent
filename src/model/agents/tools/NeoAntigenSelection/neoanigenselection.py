import asyncio
import json
import os
import sys
import uuid
import re

from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langchain_core.runnables import RunnableSerializable,RunnableLambda
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from pathlib import Path
import pandas as pd
from io import BytesIO
from typing import List, Dict, Optional, Union, AsyncIterator,Any

from src.model.agents.core import get_model
from src.model.agents.core.tool_summary_prompts import (
    NETCHOP_PROMPT,
    NETMHCPAN_PROMPT,
    BIGMHC_EL_PROMPT,
    BIGMHC_IM_PROMPT,
    RNAFOLD_PROMPT,
    PMTNET_PROMPT
)
from config import CONFIG_YAML
from src.model.agents.tools.utils.step1_protein_cleavage import step1_protein_cleavage
from src.model.agents.tools.utils.step2_pmhc_binding_affinity import step2_pmhc_binding_affinity
from src.model.agents.tools.utils.step3_pmhc_immunogenicity import step3_pmhc_immunogenicity
from src.model.agents.tools.utils.step4_pmhc_tcr_interaction import step4_pmhc_tcr_interaction
from src.model.agents.tools.utils.step6_tap_transportation_prediction import step6_tap_transportation_prediction
from src.utils.minio_utils import upload_file_to_minio,download_from_minio_uri
load_dotenv()
# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MOLLY_BUCKET = MINIO_CONFIG["molly_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
RNAFOLD_ENERGY_THRESHOLD = NEOANTIGEN_CONFIG["rnafold_energy_threshold"]
OUTPUT_TMP = CONFIG_YAML["TOOL"]["RNAFOLD"]["output_tmp_dir"]

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

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
        # minio_client.fget_object(bucket_name, object_name, local_temp_path)
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

def normalize_hla_alleles(allele_list):
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
    
    return normalized






async def run_neoanigenselection(
    input_file: str,
    mhc_allele: Optional[List[str]] = None,
    cdr3_sequence: Optional[List[str]] = None
) -> str:
    """
    运行新抗原筛选流程
    
    Args:
        input_file: 输入文件路径
        mhc_allele: MHC等位基因列表
        cdr3_sequence: CDR3序列列表
    
    Returns:
        str: JSON格式的结果字符串
    """
    # 初始化变量
    mrna_design_process_result = []
    neoantigen_message = ["--"] * 13
    cleavage_m=0
    tap_m=0
    pmhc_binding_m=0
    pmhc_immunogenicity_m=0
    tcr_m=0

    writer = get_stream_writer()
    mhc_allele=normalize_hla_alleles(mhc_allele)


    try:

        # 第一步：蛋白切割位点预测
        cleavage_result_file_path, netchop_final_result_str,cleavage_m = await step1_protein_cleavage(
            input_file, writer, mrna_design_process_result,minio_client,neoantigen_message
        )
        neoantigen_message[0] = f"{cleavage_m}/{cleavage_m}"
        neoantigen_message[1] = cleavage_result_file_path

        # 第二步：TAP转运预测
        netctlpan_file_path,netctlpan_fasta_str,tap_m,netctlpan_tool_url= await step6_tap_transportation_prediction(
            cleavage_result_file_path, netchop_final_result_str,mhc_allele, writer, mrna_design_process_result,minio_client,neoantigen_message,cleavage_m
        )
        neoantigen_message[2]=f"{tap_m}/{cleavage_m}"
        neoantigen_message[3]=netctlpan_tool_url
        # 第三步：pMHC结合亲和力预测
        bigmhc_el_result_file_path, bigmhc_el_fasta_str,pmhc_binding_ratio,pmhc_binding_m,bigmhc_el_tool_url= await step2_pmhc_binding_affinity(
            netctlpan_file_path, netctlpan_fasta_str,mhc_allele, writer, mrna_design_process_result,minio_client,neoantigen_message,tap_m
        )
        neoantigen_message[6]=pmhc_binding_ratio
        neoantigen_message[7]=bigmhc_el_tool_url
        # 第四步：pMHC免疫原性预测
        bigmhc_im_result_file_path, bigmhc_im_fasta_str,pmhc_immunogenicity_m, bigmhc_im_tool_url= await step3_pmhc_immunogenicity(
            bigmhc_el_result_file_path, writer, mrna_design_process_result,minio_client,neoantigen_message,pmhc_binding_m
        )
        neoantigen_message[8]=f"{pmhc_immunogenicity_m}/{pmhc_binding_m}"
        neoantigen_message[9]=bigmhc_im_tool_url
        # 第五步：pMHC-TCR相互作用预测
        mrna_input_file_path,tcr_m,tcr_content,pmtnet_result_tool_url= await step4_pmhc_tcr_interaction(
            bigmhc_im_result_file_path, cdr3_sequence, writer, mrna_design_process_result,minio_client,neoantigen_message,pmhc_immunogenicity_m
        
        )
        if cdr3_sequence is not None:
            neoantigen_message[10]=f"{tcr_m}/{pmhc_immunogenicity_m}"
            neoantigen_message[11]=pmtnet_result_tool_url
            neoantigen_message[12]=tcr_content
            STEP1_DESC2 = f"""
    \n## 📄 综合结论：
    \n✅ 本次筛选流程中，系统最终识别出{tcr_m}条在抗原递呈、免疫激活与T细胞识别多个维度均表现优异的个体化 neoantigen 候选肽段，建议作为后续疫苗设计重点靶点。
        """
            writer(STEP1_DESC2)
        
        
    except Exception as e:
        return json.dumps({
            "type": "text",
            "content": f"流程执行失败: {str(e)}"
        }, ensure_ascii=False)
    
    finally:
        # 返回最终结果
        return "#NEO#".join(neoantigen_message)
@tool
def NeoantigenSelection(
    input_file: str,
    mhc_allele: Optional[List[str]] = None, 
    cdr3_sequence: Optional[List[str]] = None
) -> str:
    """                                    
    NeoantigenSelection是基于用户输入的患者信息，结合已有的工具库，完成个体化neo-antigen筛选。
    Args:                                  
        input_file (str): 输入的肽段序例fasta文件路径           
        mhc_allele (Optional[List[str]]): MHC比对的等位基因。
        cdr3_sequence (Optional[List[str]]): cdr3序列。
    Returns:                               
        str: 返回高结合亲和力的肽段序例信息                                                                                                                           
    """
    try:
        result = asyncio.run(run_neoanigenselection(input_file, mhc_allele, cdr3_sequence))
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