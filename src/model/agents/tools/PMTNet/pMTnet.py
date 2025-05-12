import asyncio
import json
import sys
import os
import re
import uuid
import itertools
import pandas as pd
import aiohttp
import traceback

from minio import Minio
from minio.error import S3Error
from pathlib import Path
from langchain_core.tools import tool
from urllib.parse import urlparse
from typing import List, Dict, Optional

current_file = Path(__file__).resolve()
current_script_dir = current_file.parent
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML

pmtnet_url = CONFIG_YAML["TOOL"]["PMTNET"]["url"]
upload_dir = CONFIG_YAML["TOOL"]["PMTNET"]["upload_dir"]
download_dir = CONFIG_YAML["TOOL"]["PMTNET"]["download_dir"]
os.makedirs(upload_dir, exist_ok=True)
os.makedirs(download_dir, exist_ok=True)

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_BUCKET = MINIO_CONFIG["pmtnet_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

def upload_to_minio(local_path: str, bucket: str = MINIO_BUCKET, object_name: Optional[str] = None) -> str:
    if not object_name:
        object_name = f"inputs/{uuid.uuid4()}.csv"
    minio_client.fput_object(bucket, object_name, local_path)
    return f"minio://{bucket}/{object_name}"

def download_from_minio(minio_path: str, download_dir: str = download_dir) -> str:
    url = urlparse(minio_path)
    bucket = url.netloc
    object_name = url.path.lstrip("/")
    local_path = os.path.join(download_dir, f"{uuid.uuid4()}_{os.path.basename(object_name)}")
    minio_client.fget_object(bucket, object_name, local_path)
    return local_path

def extract_antigen_sequences(antigen_input) -> List[str]:
    if isinstance(antigen_input, list):
        return antigen_input
    elif isinstance(antigen_input, str) and antigen_input.startswith("minio://"):
        local_path = download_from_minio(antigen_input)
        sequences = []
        with open(local_path, "r") as f:
            current_seq = ""
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    if current_seq:
                        sequences.append(current_seq)
                        current_seq = ""
                else:
                    current_seq += line
            if current_seq:
                sequences.append(current_seq)
        return sequences
    else:
        raise ValueError("Antigen 输入必须是列表或 MinIO FASTA 路径")

def load_antigen_hla_pairs(input_source) -> List[Dict[str, str]]:
    if isinstance(input_source, str) and input_source.startswith("minio://"):
        local_path = download_from_minio(input_source)
        df = pd.read_csv(local_path)
        if not {"Antigen", "HLA"}.issubset(df.columns):
            raise ValueError("CSV 文件必须包含 'Antigen' 和 'HLA' 两列")
        return df[["Antigen", "HLA"]].to_dict(orient="records")
    elif isinstance(input_source, list):
        return input_source
    else:
        raise ValueError("antigen_hla_pairs 必须是 MinIO 路径或 List 格式")
def process_uploaded_fasta_to_csv(
    uploaded_fasta_path: str,
    cdr3_list: List[str],
) -> str:
    if not uploaded_fasta_path.startswith("minio://"):
        raise ValueError(" uploaded_file 必须是 MinIO 路径")
    if not uploaded_fasta_path.lower().endswith((".fa", ".fasta", ".fas")):
        raise ValueError(" 文件不是 .fasta 格式")
    if not cdr3_list:
        raise ValueError(" FASTA 格式时必须提供 cdr3_list")

    # 下载
    local_path = download_from_minio(uploaded_fasta_path)
    hla_pattern = re.compile(r"^[ABC]\*\d{2}:\d{2}$")
    sequences = []

    with open(local_path, "r") as f:
        current_pep = ""
        current_hla = ""
        for line in f:
            line = line.strip()
            if line.startswith(">") and "|" in line:
                parts = line[1:].split("|", 1)
                if len(parts) == 2:
                    current_pep = parts[0].strip()
                    current_hla = parts[1].strip()
                    if current_hla.startswith("HLA-"):
                        current_hla = current_hla[4:]
                    if not hla_pattern.fullmatch(current_hla):
                        continue
            elif line and current_pep and current_hla:
                sequences.append({
                    "Antigen": line.strip(),
                    "HLA": current_hla
                })
                current_pep, current_hla = "", ""

    if not sequences:
        raise ValueError(" FASTA 文件无有效 >peptide|HLA 项")

    # 做笛卡尔积
    rows = []
    for cdr3 in cdr3_list:
        for pair in sequences:
            rows.append({
                "CDR3": cdr3,
                "Antigen": pair["Antigen"],
                "HLA": pair["HLA"]
            })

    # 写 CSV
    df = pd.DataFrame(rows)
    tmp_file = f"{upload_dir}/{uuid.uuid4()}_pmtnet_input.csv"
    df.to_csv(tmp_file, index=False)

    try:
        return upload_to_minio(tmp_file)
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

def prepare_pmtnet_input(
    cdr3_list: List[str],
    antigen_input=None,
    hla_list: Optional[List[str]] = None,
    antigen_hla_pairs=None,
    uploaded_file: Optional[str] = None
) -> str:
    if isinstance(uploaded_file, str) and uploaded_file.startswith("minio://"):
        if uploaded_file.lower().endswith((".fa", ".fasta", ".fas")):
            if not cdr3_list:
                raise ValueError(" 当上传文件为 .fasta 且格式为 >peptide|HLA 时，必须提供 cdr3_list")
            return process_uploaded_fasta_to_csv(uploaded_file, cdr3_list)
        return uploaded_file

    hla_list = hla_list or ["A*02:01"]
    rows = []

    if antigen_hla_pairs:
        pair_list = load_antigen_hla_pairs(antigen_hla_pairs)
        for cdr3 in cdr3_list:
            for pair in pair_list:
                rows.append({
                    "CDR3": cdr3,
                    "Antigen": pair["Antigen"],
                    "HLA": pair["HLA"]
                })
    else:
        antigen_list = extract_antigen_sequences(antigen_input)
        for cdr3, antigen, hla in itertools.product(cdr3_list, antigen_list, hla_list):
            rows.append({
                "CDR3": cdr3,
                "Antigen": antigen,
                "HLA": hla
            })

    df = pd.DataFrame(rows)
    tmp_file = f"{upload_dir}/pmtnet_input_{uuid.uuid4()}.csv"
    df.to_csv(tmp_file, index=False)

    try:
        return upload_to_minio(tmp_file)
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


@tool
async def pMTnet(
                cdr3_list: Optional[List[str]] = None,
                antigen_input=None,
                hla_list: Optional[List[str]] = None,
                antigen_hla_pairs=None,
                uploaded_file: Optional[str] = None) -> str:
    """
    
    自动构造 pMTnet 输入文件并调用远程预测服务。
    
    Args:
        支持以下任意输入：
        - cdr3_list
        - antigen_input：序列列表或 minio://fasta 路径
        - hla_list：可选
        - antigen_hla_pairs：列表或 minio://csv 路径
        - uploaded_file：用户上传的 minio://csv，直接使用

    Returns:
    
        异步调用远程 pMTnet 服务接口，获取分析结果。
    
        str: pMTnet 服务返回的 JSON 格式结果
    """
    try:
        input_file_path = prepare_pmtnet_input(
                cdr3_list=cdr3_list,
                antigen_input=antigen_input,
                hla_list=hla_list,
                antigen_hla_pairs=antigen_hla_pairs,
                uploaded_file=uploaded_file
            )
        
        timeout = aiohttp.ClientTimeout(total=30)
        payload = {"input_file_dir_minio": input_file_path}
    
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(pmtnet_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f"调用远程 pMTnet 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)

if __name__ == "__main__":
    test_cdr3_list = ["CASSVASSGNIQYF"]
    # test_antigen_list = ["NLVPMVATV", "GILGFVFTL","GTHWHRSPR"]
    #####注意每个工具之间的hla的写法不同
    # test_hla_list = ["A*11:01", "A*02:01"]
    # test_uploaded_file = "minio://molly/66dd7c86-f1c4-455e-9e50-3b2a77be66c9_test_input.csv"

    async def test():
        result = await pMTnet.ainvoke({
            "cdr3_list": test_cdr3_list,
            "uploaded_file": "minio://molly/da861418-bdac-43b3-8760-853d8140ab37_bigmhc_el.fasta",
        })
        print("异步调用结果：")
        print(result)

    asyncio.run(test())