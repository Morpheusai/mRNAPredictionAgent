import aiohttp
import asyncio
import json
import os
import sys
import traceback
import uuid

from Bio import SeqIO
from io import StringIO
from langchain_core.tools import tool
from minio import Minio
from pathlib import Path
from typing import List, Optional

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]                
sys.path.append(str(project_root))
from config import CONFIG_YAML
from utils.minio_utils import upload_file_to_minio,download_from_minio_uri

immuneapp_neo_url = CONFIG_YAML["TOOL"]["IMMUNEAPP_NEO"]["url"]
LOCAL_OUTPUT_DIR = CONFIG_YAML["TOOL"]["IMMUNEAPP_NEO"]["output_tmp_dir"]
os.makedirs(LOCAL_OUTPUT_DIR, exist_ok=True)

MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_BUCKET = MINIO_CONFIG["immuneapp_neo_bucket"]



def fasta_to_peplist_txt(
    minio_path: str,
) -> str:
    """
    从 MinIO 中的 FASTA 文件提取肽段

    参数：
    - minio_path: 格式为 minio://bucket/path.fasta

    返回：
    - 转换后 .txt 文件的本地路径
    """

    
    output_dir = Path(LOCAL_OUTPUT_DIR)
    tmp_fasta_path = output_dir / f"{uuid.uuid4().hex}_input.fasta"
    peplist_path = output_dir / f"{uuid.uuid4().hex}_peplist.txt"

    download_from_minio_uri(minio_path,str(tmp_fasta_path))
    
    invalid_length = False
    with open(peplist_path, "w", encoding="utf-8") as fout:
        for record in SeqIO.parse(tmp_fasta_path, "fasta"):
            seq = str(record.seq).strip().upper()
            if seq:
                if not (8 <= len(seq) <= 12):
                    invalid_length = True
                fout.write(seq + "\n")
                
    tmp_fasta_path.unlink(missing_ok=True)
    
    if invalid_length:
        peplist_path.unlink(missing_ok=True)
        raise ValueError("有非法肽段")
    
    upload_name = f"{uuid.uuid4().hex}_peplist.txt"
    minio_upload_path=upload_file_to_minio(str(peplist_path),MINIO_BUCKET,upload_name)
    peplist_path.unlink(missing_ok=True)
    
    return minio_upload_path


@tool
async def ImmuneApp_Neo(
    input_file: str,
    alleles: Optional[List[str]] = None
) -> str:
    """
    使用 ImmuneApp-Neo 工具预测 neoepitope 的免疫原性。

    参数:
    - input_file: MinIO 文件路径，例如 minio://bucket/file.fasta
    - alleles: HLA-I 等位基因列表（如 ["HLA-A*01:01", "HLA-A*02:01"]）

    返回:
    - JSON 格式字符串，包含结果链接或错误信息
    """
    if input_file.lower().endswith((".fasta", ".fa", ".fsa", ".fas")):
        try:
            input_file = fasta_to_peplist_txt(input_file)
        except ValueError as ve:
            return json.dumps({
                "type": "text",
                "content": str(ve)
            }, ensure_ascii=False)
        
    if alleles is None:
        alleles = ["HLA-A*01:01", "HLA-A*02:01", "HLA-A*03:01", "HLA-B*07:02"]
    alleles = ",".join(alleles)
    payload = {
        "input_file": input_file,
        "alleles": alleles
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(immuneapp_neo_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f" ImmuneApp_Neo 执行失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)
if __name__ == "__main__":
    async def test():
        result = await ImmuneApp_Neo.ainvoke({
            "input_file": "minio://molly/03546884-084b-4bcf-9236-08e81048e138_peptide.fasta",
            # "input_file": "minio://molly/a329abf8-55a7-46a3-9396-f1b33f3fcb45_test_immuneapp.fas",
            "alleles": ["HLA-A*01:01", "HLA-A*02:01", "HLA-A*03:01", "HLA-B*07:02"]
        })
        print("ImmuneApp_Neo 调用结果：")
        print(result)

    asyncio.run(test())

