import json
import uuid
import requests
import time

import pandas as pd

from io import BytesIO
from minio.error import S3Error
from typing import  List

from config import CONFIG_YAML
from src.utils.minio_utils import MINIO_CLIENT
from src.agents.tools.parameters import NetctlpanParameters
from src.agents.tools.NetCTLPan.netctlpan import NetCTLpan
from src.utils.tool_input_output_api import send_tool_input_output_api
from src.utils.log import logger
from src.utils.ai_message_api import send_ai_message_to_server

NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
NETCTLPAN_THRESHOLD = NEOANTIGEN_CONFIG["netctlpan_threshold"]

handle_url = CONFIG_YAML["TOOL"]["COMMON"]["handle_tool_input_output_url"]

# . 去重
def deduplicate_fasta_by_sequence(fasta_str: str) -> str:
    lines = fasta_str.strip().split('\n')
    seen_seq = set()
    result = []
    i = 0
    while i < len(lines):
        if lines[i].startswith('>'):
            desc = lines[i]
            seq = lines[i+1] if i+1 < len(lines) else ''
            if seq not in seen_seq:
                seen_seq.add(seq)
                result.append(desc)
                result.append(seq)
            i += 2
        else:
            i += 1
    return '\n'.join(result)

async def step6_tap_transportation_prediction(
    input_parameters: NetctlpanParameters, 
    neoantigen_message,
    cleavage_m,
    patient_id,
    predict_id,
    conversation_id,
) -> tuple:
    """
    第二步：TAP转运预测阶段
    Args:
        input_parameters: netctlpan输入参数
    Returns:
        tuple: (netctlpan_result_file_path, netctlpan_fasta_str) 结果文件路径和FASTA内容
    """
    STEP2_DESC1 = f"""
## 🚚 步骤 2：TAP转运效率预测
目标：排除难以通过抗原加工通路的低效率肽段
"""
    send_ai_message_to_server(conversation_id, STEP2_DESC1)
    # 调用前置接口
    try:
        send_tool_input_output_api(
            patient_id, 
            predict_id, 
            0, 
            "NetCTLpan", 
            input_parameters.__dict__ if hasattr(input_parameters, '__dict__') else dict(input_parameters),
            flag=0
        )
    except Exception as e:
        logger.error(f"前置接口调用失败: {e}")
    # 运行NetCTLpan工具
    logger.info("开始执行NetCTLpan工具...")
    start_time = time.time()
    # 将peptide_length数组转换为逗号分隔的字符串
    peptide_length_str = ",".join(map(str, input_parameters.peptide_length))
    
    netctlpan_result = await NetCTLpan.arun({
        "input_filename": input_parameters.input_filename,
        "mhc_allele": input_parameters.mhc_allele,
        "peptide_length": peptide_length_str,
        "weight_of_tap": input_parameters.weight_of_tap,
        "weight_of_clevage": input_parameters.weight_of_clevage,
        "epi_threshold": input_parameters.epi_threshold,
        "output_threshold": input_parameters.output_threshold,
        "sort_by": input_parameters.sort_by
    })
    end_time = time.time()
    execution_time = end_time - start_time
    logger.info(f"NetCTLpan工具执行完成，耗时: {execution_time:.2f}秒")
    try:
        netctlpan_result_dict = json.loads(netctlpan_result)
        logger.info("NetCTLpan工具结果解析成功")
    except json.JSONDecodeError:
        logger.error("NetCTLpan工具结果JSON解析失败")
        raise Exception("TAP转运预测阶段NetCTLpan工具执行失败")
    try:
        send_tool_input_output_api(
            patient_id, 
            predict_id, 
            1, 
            "NetCTLpan", 
            netctlpan_result_dict,
            flag=0
        )
    except Exception as e:
        logger.error(f"后置接口调用失败: {e}")
    if netctlpan_result_dict.get("type") != "link":
        logger.error(f"NetCTLpan工具执行失败: {netctlpan_result_dict.get('content', '未知错误')}")
        raise Exception(netctlpan_result_dict.get("content", "TAP转运预测阶段NetCTLpan工具执行失败"))
    netctlpan_result_file_path = netctlpan_result_dict["url"]
    logger.info(f"NetCTLpan工具结果文件路径: {netctlpan_result_file_path}")
    
    # 读取NetCTLpan结果文件
    try:
        path_without_prefix = netctlpan_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        logger.info(f"从MinIO读取NetCTLpan结果文件: bucket={bucket_name}, object={object_name}")
        response = MINIO_CLIENT.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)
        logger.info(f"成功读取NetCTLpan结果文件，共 {len(df)} 条记录")
    except S3Error as e:
        logger.error(f"从MinIO读取NetCTLpan结果文件失败: {str(e)}")
        raise Exception(f"无法从MinIO读取NetCTLpan结果文件: {str(e)}")
    high_affinity_peptides = df[df['TAP'] >= NETCTLPAN_THRESHOLD]
    logger.info(f"筛选出 {len(high_affinity_peptides)} 条高转运效率肽段 (TAP >= {NETCTLPAN_THRESHOLD})")
    if high_affinity_peptides.empty:
        logger.warning(f"未筛选到符合TAP >= {NETCTLPAN_THRESHOLD}要求的高转运效率概率的肽段")
        STEP2_DESC6 = f"""
未筛选到符合TAP >= {NETCTLPAN_THRESHOLD}要求的高转运效率概率的肽段，筛选流程结束。
"""
        send_ai_message_to_server(conversation_id, STEP2_DESC6)
        neoantigen_message[2]=f"0/{cleavage_m}"
        neoantigen_message[3]=netctlpan_result_file_path
        raise Exception(f"未找到高亲和力肽段(TAP ≥ {NETCTLPAN_THRESHOLD})")
    
    # 构建FASTA文件内容
    fasta_content = []
    for idx, row in high_affinity_peptides.iterrows():
        peptide = row['Peptide']
        mhc_allele = row['Allele']
        fasta_content.append(f">{peptide}|{mhc_allele}")
        fasta_content.append(peptide)
    netctlpan_fasta_str = "\n".join(fasta_content)
    deduped_str = deduplicate_fasta_by_sequence(netctlpan_fasta_str)
    count = sum(1 for line in deduped_str.splitlines() if line.startswith('>'))
    
    # 上传FASTA文件到MinIO  
    uuid_name = str(uuid.uuid4())
    netctlpan_result_fasta_filename = f"{uuid_name}_netctlpan.fasta"
    try:
        fasta_bytes = deduped_str.encode('utf-8')
        
        fasta_stream = BytesIO(fasta_bytes)
        logger.info(f"上传FASTA文件到MinIO: {netctlpan_result_fasta_filename}")
        MINIO_CLIENT.put_object(
            "molly",
            netctlpan_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
        logger.info("FASTA文件上传成功")
    except Exception as e:
        logger.error(f"上传FASTA文件失败: {str(e)}")
        neoantigen_message[2]=f"0/{cleavage_m}"
        neoantigen_message[3]=f"上传FASTA文件失败: {str(e)}"
        raise Exception(f"上传FASTA文件失败: {str(e)}")
    STEP2_DESC7 = f"""
✅ 已完成转运评估，剔除部分效率较低肽段，保留**{count}个有效候选肽段**
"""    
    send_ai_message_to_server(conversation_id, STEP2_DESC7)
    return f"minio://molly/{netctlpan_result_fasta_filename}", netctlpan_fasta_str, count, netctlpan_result_file_path