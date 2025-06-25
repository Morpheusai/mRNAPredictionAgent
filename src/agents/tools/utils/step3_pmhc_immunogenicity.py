import json
import re
import uuid
import tempfile

import pandas as pd

from io import BytesIO
from typing import Tuple, List
from minio import Minio
from minio.error import S3Error

from config import CONFIG_YAML
from src.agents.tools.BigMHC.bigmhc import BigMHC_IM
from src.utils.minio_utils import download_from_minio_uri

MINIO_CONFIG = CONFIG_YAML["MINIO"]
MOLLY_BUCKET = MINIO_CONFIG["molly_bucket"]
NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
BIGMHC_IM_THRESHOLD = NEOANTIGEN_CONFIG["bigmhc_im_threshold"]


def extract_hla_and_peptides_from_fasta(
    fasta_minio_path: str
) -> Tuple[str, List[str]]:
    """
    解析 >peptide|HLA 格式的 FASTA 文件，返回原始FASTA的minio地址和所有HLA分型列表
    
    参数:
    - fasta_minio_path: MinIO路径，例如 minio://bucket/file.fasta
    
    返回:
    - tuple: (原始FASTA的minio地址, 所有HLA分型的列表)
    """
    local_path = tempfile.NamedTemporaryFile(delete=True).name
    download_from_minio_uri(fasta_minio_path, local_path)

    hla_list = []
    HLA_REGEX = re.compile(r"^(HLA-)?[ABC]\*\d{2}:\d{2}$")

    with open(local_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(">") and "|" in line:
                parts = line[1:].split("|", 1)
                if len(parts) == 2 and HLA_REGEX.fullmatch(parts[1].strip()):
                    hla = parts[1].strip()
                    if not hla.startswith("HLA-"):
                        hla = "HLA-" + hla
                    hla_list.append(hla)

    if not hla_list:
        raise ValueError("未能从FASTA中解析出合法的HLA分型")

    return (fasta_minio_path, hla_list)


async def step3_pmhc_immunogenicity(
    bigmhc_el_result_file_path: str,
    writer,
    mrna_design_process_result: list,
    minio_client: Minio,
    neoantigen_message,
    pmhc_binding_m
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
#     STEP3_DESC1 = """
# ## 第3部分-pMHC免疫原性预测
# 基于BigMHC_IM工具对上述内容进行pMHC免疫原性预测 

# \n参数设置说明：
# - MHC等位基因(mhc_allele): 指定用于预测的MHC分子类型

# 当前使用配置：
# - 选用MHC allele: HLA-A02:01
# """
    STEP3_DESC1 = """
## 💥 步骤 4：免疫原性预测
目标：评估肽段激发免疫反应的潜力
"""

    writer(STEP3_DESC1)
    mrna_design_process_result.append(STEP3_DESC1)

    input_file,mhc_alleles = extract_hla_and_peptides_from_fasta(bigmhc_el_result_file_path)
    # 运行BigMHC_IM工具
    bigmhc_im_result = await BigMHC_IM.arun({
        "input_file": input_file,"mhc_alleles":mhc_alleles
    })
    try:
        bigmhc_im_result_dict = json.loads(bigmhc_im_result)
    except json.JSONDecodeError:
        neoantigen_message[8]=f"0/{pmhc_binding_m}"
        neoantigen_message[9]="pMHC免疫原性预测阶段BigMHC_im工具执行失败"
        raise Exception("pMHC免疫原性预测阶段BigMHC_im工具执行失败")
    
    if bigmhc_im_result_dict.get("type") != "link":
        neoantigen_message[8]=f"0/{pmhc_binding_m}"
        neoantigen_message[9]="pMHC免疫原性预测阶段BigMHC_im工具执行失败"
        raise Exception(bigmhc_im_result_dict.get("content", "pMHC免疫原性预测阶段BigMHC_im工具执行失败"))
    
    # 获取结果文件路径
    bigmhc_im_result_file_path = bigmhc_im_result_dict["url"]
    
    # 步骤中间描述
    INSERT_SPLIT = \
    f"""
    """   
    # writer(INSERT_SPLIT)    
    STEP3_DESC2 = f"""
### 第3部分-pMHC免疫原性预测结束\n
pMHC免疫原性预测预测结果已获取，结果如下：\n
{bigmhc_im_result_dict['content']}。
"""
    # writer(STEP3_DESC2)
    mrna_design_process_result.append(STEP3_DESC2)
    
    # 读取BigMHC_IM结果文件
    try:
        path_without_prefix = bigmhc_im_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        response = minio_client.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)
    except S3Error as e:
        neoantigen_message[8]=f"0/{pmhc_binding_m}"
        neoantigen_message[9]=f"无法从MinIO读取BigMHC_IM结果文件: {str(e)}"
        raise Exception(f"无法从MinIO读取BigMHC_IM结果文件: {str(e)}")
    
    # 步骤筛选描述
    STEP3_DESC3 = f"""
### 第3部分-pMHC免疫原性预测后筛选
接下来为您筛选符合BigMHC_IM >={BIGMHC_IM_THRESHOLD}要求的高免疫原性的肽段
"""
    # writer(STEP3_DESC3)
    mrna_design_process_result.append(STEP3_DESC3)
    
    # 筛选高免疫原性肽段
    high_affinity_peptides = df[df['BigMHC_IM'] >= BIGMHC_IM_THRESHOLD]
    
    if high_affinity_peptides.empty:
        STEP3_DESC4 = f"""
未筛选到符合BigMHC_IM >= {BIGMHC_IM_THRESHOLD}要求的高免疫原性的肽段，筛选流程结束。
"""
        writer(STEP3_DESC4)
        mrna_design_process_result.append(STEP3_DESC4)
        neoantigen_message[8]=f"0/{pmhc_binding_m}"
        neoantigen_message[9]=bigmhc_im_result_file_path
        raise Exception(f"未找到高免疫原性肽段(BigMHC_IM ≥ {BIGMHC_IM_THRESHOLD})")
    
    # 构建FASTA文件内容
    fasta_content = []
    count =0
    for idx, row in high_affinity_peptides.iterrows():
        peptide = row['pep']
        mhc_allele = row['mhc']
        fasta_content.append(f">{peptide}|{mhc_allele}")
        fasta_content.append(peptide)
        count +=1
    
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
        neoantigen_message[8]=f"0/{pmhc_binding_m}"
        neoantigen_message[9]=f"上传FASTA文件失败: {str(e)}"
        raise Exception(f"上传FASTA文件失败: {str(e)}")
    
    # 步骤完成描述
    STEP3_DESC5 = f"""
### 第3部分-pMHC免疫原性预测后筛选结束
已完成筛选符合要求的高免疫原性的肽段，结果如下：
```fasta
{bigmhc_im_fasta_str}
```\n
"""
    # writer(STEP3_DESC5)
    mrna_design_process_result.append(STEP3_DESC5)
    STEP3_DESC5 = f"""
✅ 在候选肽段中，系统筛选出**{count}个具有较高免疫原性评分的肽段**
"""
    writer(STEP3_DESC5)
    
    return f"minio://molly/{bigmhc_im_result_fasta_filename}", bigmhc_im_fasta_str,count,bigmhc_im_result_file_path,bigmhc_im_result_dict["content"]
