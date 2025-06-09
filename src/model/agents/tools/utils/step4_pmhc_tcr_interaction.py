import json
import sys
import uuid

from typing import List, Optional
from minio import Minio
from io import BytesIO
import pandas as pd
from pathlib import Path
from langgraph.config import get_stream_writer
from src.model.agents.tools.PMTNet.pMTnet import pMTnet

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML

MINIO_CONFIG = CONFIG_YAML["MINIO"]
MOLLY_BUCKET = MINIO_CONFIG["molly_bucket"]
NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
PMTNET_RANK = NEOANTIGEN_CONFIG["pmtnet_rank"]

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
## 🧩 步骤 5：TCR识别可能性评估（患者提供CDR3序列）
目标：分析候选肽段是否可能被患者T细胞特异性识别
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
对上述内容使用pMTnet工具进行pMHC-TCR相互作用预测

\n参数设置说明:
- MHC等位基因(mhc_allele): 指定用于预测的MHC分子类型
- cdr3序列(cdr3): T细胞受体(TCR)的互补决定区3序列，用于评估TCR-pMHC相互作用潜力

当前使用配置：
- 选用MHC allele: HLA-A02:01
- 选用cdr3: {cdr3_sequence}
"""
    # writer(STEP4_DESC2)
    mrna_design_process_result.append(STEP4_DESC2)
    
    # 运行pMTnet工具
    pmtnet_result = await pMTnet.arun({
        "cdr3_list": cdr3_sequence,
        "uploaded_file": bigmhc_im_result_file_path
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
✅ 已识别出{count}条与患者TCR具有较高匹配可能性的肽段，作为优选候选
"""
    writer(STEP4_DESC6)
    
    return f"minio://molly/{pmtnet_filtered_fasta_filename}",count,pmtnet_result_dict['content'],pmtnet_result_file_path