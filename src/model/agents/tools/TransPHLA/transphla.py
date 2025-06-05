import aiohttp
import asyncio
import json
import os
import sys
import uuid
import traceback

from dotenv import load_dotenv
from typing import List
from minio import Minio
from minio.error import S3Error
from langchain_core.tools import tool
from pathlib import Path

from utils.minio_utils import upload_file_to_minio
current_file = Path(__file__).resolve()
project_root = current_file.parents[5]                
sys.path.append(str(project_root))
from config import CONFIG_YAML
from src.utils.log import logger
load_dotenv()

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MOLLY_BUCKET = MINIO_CONFIG["molly_bucket"]


transphla_url = CONFIG_YAML["TOOL"]["TRANSPHLA"]["url"]
transphla_input_tmp_dir = CONFIG_YAML["TOOL"]["TRANSPHLA"]["input_tmp_dir"]
hla_peptide_mapping_path = CONFIG_YAML["TOOL"]["TRANSPHLA"]["hla_peptide_mapping_path"]

def generate_fasta(hla_list: List[str]):
    """
    从hla_list中找到对应映射的肽段，并存到.fasta文件中
    
    Args:
        hla_list (List): hla分型
    
    Returns:
        str: 新文件的MinIO路径
    """


    # 1. 加载映射库
    with open(hla_peptide_mapping_path) as f:
        hla_map = json.load(f)
    output_path = f"{transphla_input_tmp_dir}/{uuid.uuid4().hex}_output.fasta"

    # 2. 处理并写入FASTA
    with open(output_path, 'w') as out:
        for i, hla in enumerate(hla_list):
            if hla in hla_map:
                peptide = hla_map[hla]
                # 如果不是最后一个条目，才加换行符
                line_end = "\n" if i < len(hla_list) - 1 else ""
                out.write(f">{hla}\n{peptide}{line_end}")
            else:
                logger.warning(f"No peptide mapping found for {hla}")

    # 3. FASTA写入minio存储系统中
    try:
        random_id = uuid.uuid4().hex
        new_object_name = f"{random_id}_hlas.fasta"
        upload_file_to_minio(output_path,MOLLY_BUCKET,new_object_name)
        Path(output_path).unlink(missing_ok=True)
        return f"minio://molly/{new_object_name}"

    except S3Error as e:
        raise Exception(f"MinIO操作失败: {e}")
    except Exception as e:
        raise Exception(f"处理失败: {e}")
            



@tool
async def TransPHLA_AOMP(
    peptide_file: str,
    alleles: List[str],
    threshold: float = 0.5,
    cut_length: int = 10,
    cut_peptide: bool = True
) -> str:
    """
    使用 TransPHLA_AOMP 工具预测肽段与 HLA 的结合能力，并自动返回结果文件链接。

    参数说明：
    - peptide_file: MinIO 中的肽段 FASTA 文件路径（如 minio://bucket/peptides.fasta）
    - alleles:  等位基因列表（如 ["HLA-A*01:01", "HLA-A*02:01"]）
    - threshold: 绑定预测阈值，默认 0.5
    - cut_length: 肽段最大切割长度
    - cut_peptide: 是否启用肽段切割处理

    返回：
    - JSON 字符串，包含 URL 及 markdown 格式的输出说明
    """
    alleles=generate_fasta(alleles)
    payload = {
        "peptide_file": peptide_file,
        "hla_file": alleles,
        "threshold": threshold,
        "cut_length": cut_length,
        "cut_peptide": cut_peptide
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(transphla_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f" TransPHLA工具运行失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)

if __name__ == "__main__":
    async def test():
        result = await TransPHLA_AOMP.ainvoke({
            "peptide_file": "minio://molly/c2a3fc7e-acdb-483c-8ce4-3532ebb96136_peptides.fasta",
            "hla_file": "minio://molly/29959599-2e39-4a66-a22d-ccfb86dedd21_hlas.fasta",
            "threshold": 0.5,
            "cut_length": 10,
            "cut_peptide": True
        })
        print("TransPHLA 调用结果：")
        print(result)

    asyncio.run(test())
#     [
#     "HLA-A*11:01",
#     "HLA-A*11:01",
#     "HLA-A*68:01",
#     "HLA-A*11:01",
#     "HLA-A*11:01",
#     "HLA-A*68:01",
#     "HLA-A*11:01",
#     "HLA-A*11:01",
#     "HLA-A*68:01",
#     "HLA-A*68:01",
#     "HLA-A*68:01"
# ]