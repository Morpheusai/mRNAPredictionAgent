import json
import sys
import uuid

from typing import Tuple, List
from minio import Minio
from io import BytesIO
import pandas as pd
from pathlib import Path
from minio.error import S3Error
from langgraph.config import get_stream_writer
from src.model.agents.tools.BigMHC.bigmhc import BigMHC_IM

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML

MINIO_CONFIG = CONFIG_YAML["MINIO"]
MOLLY_BUCKET = MINIO_CONFIG["molly_bucket"]
NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
BIGMHC_IM_THRESHOLD = NEOANTIGEN_CONFIG["bigmhc_im_threshold"]

async def step3_pmhc_immunogenicity(
    bigmhc_el_result_file_path: str,
    writer,
    mrna_design_process_result: list,
    minio_client: Minio
) -> tuple:
    """
    第三步：pMHC免疫原性预测
    
    Args:
        bigmhc_el_result_file_path: BigMHC_EL结果文件路径
        writer: 流式输出写入器
        mrna_design_process_result: 过程结果记录列表
    
    Returns:
        tuple: (bigmhc_im_result_file_path, fasta_str) 结果文件路径和FASTA内容
    """
    # 步骤开始描述
    STEP3_DESC1 = """
## 第3部分-pMHC免疫原性预测
基于BigMHC_IM工具对上述内容进行pMHC免疫原性预测 

\n参数设置说明：
- MHC等位基因(mhc_allele): 指定用于预测的MHC分子类型

当前使用配置：
- 选用MHC allele: HLA-A02:01
"""
    writer(STEP3_DESC1)
    mrna_design_process_result.append(STEP3_DESC1)
    
    # 运行BigMHC_IM工具
    bigmhc_im_result = await BigMHC_IM.arun({
        "input_file": bigmhc_el_result_file_path
    })
    
    try:
        bigmhc_im_result_dict = json.loads(bigmhc_im_result)
    except json.JSONDecodeError:
        raise Exception("pMHC免疫原性预测阶段BigMHC_im工具执行失败")
    
    if bigmhc_im_result_dict.get("type") != "link":
        raise Exception(bigmhc_im_result_dict.get("content", "pMHC免疫原性预测阶段BigMHC_im工具执行失败"))
    
    # 获取结果文件路径
    bigmhc_im_result_file_path = bigmhc_im_result_dict["url"]
    
    # 步骤中间描述
    INSERT_SPLIT = \
    f"""
    """   
    writer(INSERT_SPLIT)    
    STEP3_DESC2 = f"""
### 第3部分-pMHC免疫原性预测结束\n
pMHC免疫原性预测预测结果已获取，结果如下：\n
{bigmhc_im_result_dict['content']}。
"""
    writer(STEP3_DESC2)
    mrna_design_process_result.append(STEP3_DESC2)
    
    # 读取BigMHC_IM结果文件
    try:
        path_without_prefix = bigmhc_im_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        response = minio_client.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)
    except S3Error as e:
        raise Exception(f"无法从MinIO读取BigMHC_IM结果文件: {str(e)}")
    
    # 步骤筛选描述
    STEP3_DESC3 = f"""
### 第3部分-pMHC免疫原性预测后筛选
接下来为您筛选符合BigMHC_IM >={BIGMHC_IM_THRESHOLD}要求的高免疫原性的肽段
"""
    writer(STEP3_DESC3)
    mrna_design_process_result.append(STEP3_DESC3)
    
    # 筛选高免疫原性肽段
    high_affinity_peptides = df[df['BigMHC_IM'] >= BIGMHC_IM_THRESHOLD]
    
    if high_affinity_peptides.empty:
        STEP3_DESC4 = f"""
### 第3部分-pMHC免疫原性预测后筛选
未筛选到符合BigMHC_IM >= {BIGMHC_IM_THRESHOLD}要求的高免疫原性的肽段，筛选流程结束。
"""
        writer(STEP3_DESC4)
        mrna_design_process_result.append(STEP3_DESC4)
        raise Exception(f"未找到高免疫原性肽段(BigMHC_IM ≥ {BIGMHC_IM_THRESHOLD})")
    
    # 构建FASTA文件内容
    fasta_content = []
    for idx, row in high_affinity_peptides.iterrows():
        peptide = row['pep']
        mhc_allele = row['mhc']
        fasta_content.append(f">{peptide}|{mhc_allele}")
        fasta_content.append(peptide)
    
    bigmhc_im_fasta_str = "\n".join(fasta_content)
    
    # 上传FASTA文件到MinIO
    uuid_name = str(uuid.uuid4())
    bigmhc_im_result_fasta_filename = f"{uuid_name}_bigmhc_im.fasta"
    
    try:
        fasta_bytes = bigmhc_im_fasta_str.encode('utf-8')
        fasta_stream = BytesIO(fasta_bytes)
        minio_client.put_object(
            MOLLY_BUCKET,
            bigmhc_im_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
    except Exception as e:
        raise Exception(f"上传FASTA文件失败: {str(e)}")
    
    # 步骤完成描述
    STEP3_DESC5 = f"""
### 第3部分-pMHC免疫原性预测后筛选结束
已完成筛选符合要求的高免疫原性的肽段，结果如下：
```fasta
{bigmhc_im_fasta_str}
```\n
"""
    writer(STEP3_DESC5)
    mrna_design_process_result.append(STEP3_DESC5)
    
    return f"minio://molly/{bigmhc_im_result_fasta_filename}", bigmhc_im_fasta_str
