import json
import uuid
import re
import os

from typing import List
from typing import List, Tuple
from minio import Minio
from io import BytesIO
import pandas as pd
from src.model.agents.tools.PMTNet.pMTnet import pMTnet
from src.utils.minio_utils import download_from_minio_uri

from config import CONFIG_YAML

MINIO_CONFIG = CONFIG_YAML["MINIO"]
MOLLY_BUCKET = MINIO_CONFIG["molly_bucket"]
NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
PMTNET_RANK = NEOANTIGEN_CONFIG["pmtnet_rank"]
download_dir = CONFIG_YAML["TOOL"]["PMTNET"]["download_dir"]

def extract_hla_from_fasta(
    uploaded_fasta_path: str,
) -> Tuple[str, List[str]]:
    """
    从FASTA文件中提取HLA分型列表
    参数:
        uploaded_fasta_path: MinIO文件路径 (格式: minio://bucket/path/to/file.fasta)
    返回:
        tuple: (原始文件路径, HLA分型列表)
    异常:
        ValueError: 当文件路径无效或FASTA格式不符合要求时抛出
    """
    # 输入验证
    if not uploaded_fasta_path.startswith("minio://"):
        raise ValueError("输入文件必须是MinIO路径 (以minio://开头)")
    
    if not uploaded_fasta_path.lower().endswith((".fa", ".fasta", ".fas")):
        raise ValueError("文件不是FASTA格式 (.fa/.fasta/.fas)")

    # HLA格式正则表达式
    hla_pattern = re.compile(r"^[ABC]\*\d{2}:\d{2}$")
    hla_list = []
    # 下载文件（如果需要）
    local_path = download_from_minio_uri(uploaded_fasta_path, download_dir)
    
    try:
        with open(local_path, "r") as f:
            current_hla = ""
            for line in f:
                line = line.strip()
                if line.startswith(">") and "|" in line:
                    # 解析HLA部分
                    hla_part = line.split("|")[-1].strip()
                    if hla_part.startswith("HLA-"):
                        hla_part = hla_part[4:]
                    
                    # 验证并记录HLA分型
                    if hla_pattern.fullmatch(hla_part):
                        # if hla_part not in hla_list:  # 避免重复
                        hla_list.append(hla_part)
    
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)
    
    return uploaded_fasta_path, hla_list


async def step4_pmhc_tcr_interaction(
    bigmhc_im_result_file_path: str,
    cdr3_sequence: List[str],
    writer,
    mrna_design_process_result: list,
    minio_client: Minio,
    neoantigen_message,
    pmhc_immunogenicity_m
) -> str:
    """
    第四步：pMHC-TCR相互作用预测
    
    Args:
        bigmhc_im_result_file_path: BigMHC_IM结果文件路径
        cdr3_sequence: CDR3序列列表
        writer: 流式输出写入器
        mrna_design_process_result: 过程结果记录列表
    
    Returns:
        str: mRNA输入文件路径
    """
    if not cdr3_sequence:
#         STEP4_DESC1 = \
# f"""
# ## 第4部分-pMHC-TCR相互作用预测
# 未检测到您提供了CDR3序列，无法进行pMHC-TCR预测。
# """   
        STEP4_DESC1 = \
f"""
**未在病历中检测到CDR3序列，不能进行pMHC-TCR相互作用预测，筛选流程结束**
"""   
        writer(STEP4_DESC1)
        mrna_design_process_result.append(STEP4_DESC1)
        return json.dumps(
            {
                "type": "text",
                "content": "\n".join(mrna_design_process_result)
            },
            ensure_ascii=False,
        )           
    
    # 步骤开始描述
    STEP4_DESC2 = f"""
## 第4部分-pMHC-TCR相互作用预测
对上述内容进行pMHC-TCR相互作用预测
设置参数,  cdr3序列：{cdr3_sequence}
"""
    # writer(STEP4_DESC2)
    mrna_design_process_result.append(STEP4_DESC2)

    input_file,mhc_alleles=extract_hla_from_fasta(bigmhc_im_result_file_path)
    # 运行pMTnet工具
    pmtnet_result = await pMTnet.arun({
        "cdr3_list": cdr3_sequence,
        "input_file": input_file,
        "mhc_alleles": mhc_alleles
    })
    
    try:
        pmtnet_result_dict = json.loads(pmtnet_result)
    except json.JSONDecodeError:
        neoantigen_message[10]=f"0/{pmhc_immunogenicity_m}"
        neoantigen_message[11]="pMHC-TCR相互作用预测阶段pMTnet工具执行失败"
        raise Exception("pMHC-TCR相互作用预测阶段pMTnet工具执行失败")
    
    if pmtnet_result_dict.get("type") != "link":
        neoantigen_message[10]=f"0/{pmhc_immunogenicity_m}"
        neoantigen_message[11]="pMHC-TCR相互作用预测阶段pMTnet工具执行失败"
        raise Exception(pmtnet_result_dict.get("content", "pMHC-TCR相互作用预测阶段pMTnet工具执行失败"))
    
    pmtnet_result_file_path = pmtnet_result_dict["url"]
    
    # 步骤中间描述
    INSERT_SPLIT = \
    f"""
    """   
    # writer(INSERT_SPLIT)    
    STEP4_DESC3 = f"""
### 第4部分-pMHC-TCR相互作用预测结束\n
结果如下:\n
{pmtnet_result_dict['content']}\n
"""
    # writer(STEP4_DESC3)
    mrna_design_process_result.append(STEP4_DESC3)
    
    # 读取pMTnet结果文件
    try:
        path_without_prefix = pmtnet_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        response = minio_client.get_object(bucket_name, object_name)
        csv_data = BytesIO(response.read())
        df = pd.read_csv(csv_data)
    except Exception as e:
        neoantigen_message[10]=f"0/{pmhc_immunogenicity_m}"
        neoantigen_message[11]=f"读取pMTnet结果文件失败: {str(e)}"
        raise Exception(f"读取pMTnet结果文件失败: {str(e)}")
    
    # 步骤筛选描述
    STEP4_DESC4 = f"""
### 第4部分-pMHC-TCR相互作用预测后筛选
接下来为您筛选符合PMTNET_Rank >={PMTNET_RANK}要求的的肽段，请稍后。\n
"""
    # writer(STEP4_DESC4)
    mrna_design_process_result.append(STEP4_DESC4)
    
    # 筛选高Rank肽段
    high_rank_peptides = df[df['Rank'] >= PMTNET_RANK]
    
    if high_rank_peptides.empty:
        STEP4_DESC5 = f"""
未找到Rank ≥ {PMTNET_RANK}的高亲和力肽段，筛选流程结束。
"""
        writer(STEP4_DESC5)
        mrna_design_process_result.append(STEP4_DESC5)
        neoantigen_message[10]=f"0/{pmhc_immunogenicity_m}"
        neoantigen_message[11]=pmtnet_result_file_path
        raise Exception(f"未找到Rank ≥ {PMTNET_RANK}的高亲和力肽段")
    
    # 构建FASTA文件内容
    fasta_content = []
    count =0 
    for idx, row in high_rank_peptides.iterrows():
        peptide = row['Antigen']
        mhc_allele = row['HLA']
        fasta_content.append(f">{peptide}|{mhc_allele}")
        fasta_content.append(peptide)
        count +=1
    
    pmtnet_fasta_str = "\n".join(fasta_content)
    
    # 上传FASTA文件到MinIO
    uuid_name = str(uuid.uuid4())
    pmtnet_filtered_fasta_filename = f"{uuid_name}_pmtnet_filtered.fasta"
    
    try:
        fasta_bytes = pmtnet_fasta_str.encode('utf-8')
        fasta_stream = BytesIO(fasta_bytes)
        minio_client.put_object(
            MOLLY_BUCKET,
            pmtnet_filtered_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
    except Exception as e:
        neoantigen_message[10]=f"0/{pmhc_immunogenicity_m}"
        neoantigen_message[11]=f"上传FASTA文件失败: {str(e)}"
        raise Exception(f"上传FASTA文件失败: {str(e)}")
    
    # 步骤完成描述
    STEP4_DESC6 = f"""
### 第4部分-pMHC-TCR相互作用预测后筛选
已完成筛选pMHC-TCR相互作用预测的肽段，结果如下：
```
{pmtnet_fasta_str}
```\n
"""
    # writer(STEP4_DESC6)
    mrna_design_process_result.append(STEP4_DESC6)
    STEP4_DESC6 = f"""
✅ 已识别出**{count}条与患者TCR具有较高匹配可能性的肽段**，作为优选候选
"""
    writer(STEP4_DESC6)
    
    return f"minio://molly/{pmtnet_filtered_fasta_filename}",count,pmtnet_result_dict['content'],pmtnet_result_file_path