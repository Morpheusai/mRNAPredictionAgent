import json
import re
import uuid
import tempfile
import time

import pandas as pd

from io import BytesIO
from typing import Tuple, List
from minio.error import S3Error

from config import CONFIG_YAML
from src.utils.minio_utils import MINIO_CLIENT
from src.agents.tools.BigMHC.bigmhc import BigMHC_IM
from src.agents.tools.parameters import BigmhcIMParameters
from src.utils.minio_utils import download_from_minio_uri
from src.utils.tool_input_output_api import send_tool_input_output_api
from src.utils.log import logger

MINIO_CONFIG = CONFIG_YAML["MINIO"]
MOLLY_BUCKET = MINIO_CONFIG["molly_bucket"]
NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
BIGMHC_IM_THRESHOLD = NEOANTIGEN_CONFIG["bigmhc_im_threshold"]
handle_url = CONFIG_YAML["TOOL"]["COMMON"]["handle_tool_input_output_url"]


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
    input_parameters: BigmhcIMParameters,
    writer,
    neoantigen_message,
    pmhc_binding_m,
    patient_id,
    predict_id,
) -> tuple:
    """
    第三步：pMHC免疫原性预测
    
    Args:
        input_parameters: BigMHC_IM输入参数
        writer: 流式输出写入器
    
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

    input_file, mhc_alleles = extract_hla_and_peptides_from_fasta(input_parameters.input_filename)
    mhc_allele = ",".join(mhc_alleles)
    
    # 调用前置接口
    try:
        send_tool_input_output_api(
            patient_id, 
            predict_id, 
            0, 
            "BigMHC_IM", 
            input_parameters.__dict__ if hasattr(input_parameters, '__dict__') else dict(input_parameters)
        )
    except Exception as e:
        logger.error(f"前置接口调用失败: {e}")
    
    # 运行BigMHC_IM工具
    logger.info("开始执行BigMHC_IM工具...")
    start_time = time.time()
    bigmhc_im_result = await BigMHC_IM.arun({
        "input_filename": input_file,
        "mhc_allele":mhc_allele
    })
    end_time = time.time()
    execution_time = end_time - start_time
    logger.info(f"BigMHC_IM工具执行完成，耗时: {execution_time:.2f}秒")
    try:
        bigmhc_im_result_dict = json.loads(bigmhc_im_result)
        logger.info("BigMHC_IM工具结果解析成功")
    except json.JSONDecodeError:
        logger.error("BigMHC_IM工具结果JSON解析失败")
        neoantigen_message[8]=f"0/{pmhc_binding_m}"
        neoantigen_message[9]="pMHC免疫原性预测阶段BigMHC_im工具执行失败"
        raise Exception("pMHC免疫原性预测阶段BigMHC_im工具执行失败")
    # 调用后置接口
    try:
        send_tool_input_output_api(
            patient_id, 
            predict_id, 
            1, 
            "BigMHC_IM", 
            bigmhc_im_result_dict
        )
    except Exception as e:
        logger.error(f"后置接口调用失败: {e}")

    if bigmhc_im_result_dict.get("type") != "link":
        logger.error(f"BigMHC_IM工具执行失败: {bigmhc_im_result_dict.get('content', '未知错误')}")
        neoantigen_message[8]=f"0/{pmhc_binding_m}"
        neoantigen_message[9]="pMHC免疫原性预测阶段BigMHC_im工具执行失败"
        raise Exception(bigmhc_im_result_dict.get("content", "pMHC免疫原性预测阶段BigMHC_im工具执行失败"))
    
    # 获取结果文件路径
    bigmhc_im_result_file_path = bigmhc_im_result_dict["url"]
    logger.info(f"BigMHC_IM工具结果文件路径: {bigmhc_im_result_file_path}")
    
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
    
    # 读取BigMHC_IM结果文件
    try:
        path_without_prefix = bigmhc_im_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        logger.info(f"从MinIO读取BigMHC_IM结果文件: bucket={bucket_name}, object={object_name}")
        response = MINIO_CLIENT.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)
        logger.info(f"成功读取BigMHC_IM结果文件，共 {len(df)} 条记录")
    except S3Error as e:
        logger.error(f"从MinIO读取BigMHC_IM结果文件失败: {str(e)}")
        neoantigen_message[8]=f"0/{pmhc_binding_m}"
        neoantigen_message[9]=f"无法从MinIO读取BigMHC_IM结果文件: {str(e)}"
        raise Exception(f"无法从MinIO读取BigMHC_IM结果文件: {str(e)}")
    
    # 步骤筛选描述
    STEP3_DESC3 = f"""
### 第3部分-pMHC免疫原性预测后筛选
接下来为您筛选符合BigMHC_IM >={BIGMHC_IM_THRESHOLD}要求的高免疫原性的肽段
"""
    # writer(STEP3_DESC3)
    
    # 筛选高免疫原性肽段
    high_affinity_peptides = df[df['BigMHC_IM'] >= BIGMHC_IM_THRESHOLD]
    logger.info(f"筛选出 {len(high_affinity_peptides)} 条高免疫原性肽段 (BigMHC_IM >= {BIGMHC_IM_THRESHOLD})")
    
    if high_affinity_peptides.empty:
        logger.warning(f"未筛选到符合BigMHC_IM >= {BIGMHC_IM_THRESHOLD}要求的高免疫原性的肽段")
        STEP3_DESC4 = f"""
未筛选到符合BigMHC_IM >= {BIGMHC_IM_THRESHOLD}要求的高免疫原性的肽段，筛选流程结束。
"""
        writer(STEP3_DESC4)
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
        logger.info(f"上传FASTA文件到MinIO: {bigmhc_im_result_fasta_filename}")
        MINIO_CLIENT.put_object(
            MOLLY_BUCKET,
            bigmhc_im_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
        logger.info("FASTA文件上传成功")
    except Exception as e:
        logger.error(f"上传FASTA文件失败: {str(e)}")
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
    STEP3_DESC5 = f"""
✅ 在候选肽段中，系统筛选出**{count}个具有较高免疫原性评分的肽段**
"""
    writer(STEP3_DESC5)
    

    
    return f"minio://molly/{bigmhc_im_result_fasta_filename}", bigmhc_im_fasta_str,count,bigmhc_im_result_file_path,bigmhc_im_result_dict["content"]
