import asyncio
import json
import os
import uuid
import itertools
import pandas as pd
import aiohttp
import traceback

from langchain_core.tools import tool
from typing import List, Optional

from src.utils.minio_utils import upload_file_to_minio,download_from_minio_uri
from config import CONFIG_YAML

pmtnet_url = CONFIG_YAML["TOOL"]["PMTNET"]["url"]
upload_dir = CONFIG_YAML["TOOL"]["PMTNET"]["upload_dir"]
download_dir = CONFIG_YAML["TOOL"]["PMTNET"]["download_dir"]
os.makedirs(upload_dir, exist_ok=True)
os.makedirs(download_dir, exist_ok=True)

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_BUCKET = MINIO_CONFIG["pmtnet_bucket"]



def extract_antigen_sequences(input_file) -> List[str]:

    if not (isinstance(input_file, str) and input_file.startswith("minio://")):
        raise ValueError("输入必须是MinIO路径 (格式: minio://bucket/path)")
    local_path = None
    try:
        # 从MinIO下载文件
        local_path = download_from_minio_uri(input_file, download_dir)
        
        sequences = []
        current_seq = ""
        with open(local_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    if current_seq:  # 保存上一个序列
                        sequences.append(current_seq)
                        current_seq = ""
                else:
                    current_seq += line
            
            if current_seq:  # 添加最后一个序列
                sequences.append(current_seq)
        
        if not sequences:
            raise ValueError("FASTA文件中未找到有效肽序列")
            
        return sequences
        
    finally:
        # 确保删除临时文件
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                raise(f"警告: 无法删除临时文件 {local_path}: {e}")
    

# def load_antigen_hla_pairs(input_source) -> List[Dict[str, str]]:
#     if isinstance(input_source, str) and input_source.startswith("minio://"):
#         local_path = download_from_minio_uri(input_source,download_dir)
#         df = pd.read_csv(local_path)
#         if not {"Antigen", "HLA"}.issubset(df.columns):
#             raise ValueError("CSV 文件必须包含 'Antigen' 和 'HLA' 两列")
#         return df[["Antigen", "HLA"]].to_dict(orient="records")
#     elif isinstance(input_source, list):
#         return input_source
#     else:
#         raise ValueError("antigen_hla_pairs 必须是 MinIO 路径或 List 格式")
# def process_uploaded_fasta_to_csv(
#     uploaded_fasta_path: str,
#     cdr3_list: List[str],
# ) -> str:
#     if not uploaded_fasta_path.startswith("minio://"):
#         raise ValueError(" uploaded_file 必须是 MinIO 路径")
#     if not uploaded_fasta_path.lower().endswith((".fa", ".fasta", ".fas")):
#         raise ValueError(" 文件不是 .fasta 格式")
#     if not cdr3_list:
#         raise ValueError(" FASTA 格式时必须提供 cdr3_list")

#     # 下载
#     local_path = download_from_minio_uri(uploaded_fasta_path,download_dir)
#     hla_pattern = re.compile(r"^[ABC]\*\d{2}:\d{2}$")
#     sequences = []

#     with open(local_path, "r") as f:
#         current_pep = ""
#         current_hla = ""
#         for line in f:
#             line = line.strip()
#             if line.startswith(">") and "|" in line:
#                 parts = line[1:].split("|", 1)
#                 if len(parts) == 2:
#                     current_pep = parts[0].strip()
#                     current_hla = parts[1].strip()
#                     if current_hla.startswith("HLA-"):
#                         current_hla = current_hla[4:]
#                     if not hla_pattern.fullmatch(current_hla):
#                         continue
#             elif line and current_pep and current_hla:
#                 sequences.append({
#                     "Antigen": line.strip(),
#                     "HLA": current_hla
#                 })
#                 current_pep, current_hla = "", ""

#     if not sequences:
#         raise ValueError(" FASTA 文件无有效 >peptide|HLA 项")

#     # 做笛卡尔积
#     rows = []
#     for cdr3 in cdr3_list:
#         for pair in sequences:
#             rows.append({
#                 "CDR3": cdr3,
#                 "Antigen": pair["Antigen"],
#                 "HLA": pair["HLA"]
#             })

#     # 写 CSV
#     df = pd.DataFrame(rows)
#     tmp_file = f"{upload_dir}/{uuid.uuid4()}_pmtnet_input.csv"
#     df.to_csv(tmp_file, index=False)

#     try:
#         object_name = f"inputs/{uuid.uuid4()}.csv"
#         return upload_file_to_minio(tmp_file,MINIO_BUCKET,object_name)
#     finally:
#         if os.path.exists(tmp_file):
#             os.remove(tmp_file)

def prepare_pmtnet_input(
    cdr3_list: List[str],
    input_file=str,
    mhc_alleles: Optional[List[str]] = None,
) -> str:
    # if isinstance(uploaded_file, str) and uploaded_file.startswith("minio://"):
    #     if uploaded_file.lower().endswith((".fa", ".fasta", ".fas")):
    #         if not cdr3_list:
    #             raise ValueError(" 当上传文件为 .fasta 且格式为 >peptide|HLA 时，必须提供 cdr3_list")
    #         return process_uploaded_fasta_to_csv(uploaded_file, cdr3_list)
    #     return uploaded_file

    mhc_alleles = mhc_alleles or ["A*02:01"]
    rows = []

    # if antigen_hla_pairs:
    #     pair_list = load_antigen_hla_pairs(antigen_hla_pairs)
    #     for cdr3 in cdr3_list:
    #         for pair in pair_list:
    #             rows.append({
    #                 "CDR3": cdr3,
    #                 "Antigen": pair["Antigen"],
    #                 "HLA": pair["HLA"]
    #             })
    # else:
    antigen_list = extract_antigen_sequences(input_file)
    for cdr3, antigen, hla in itertools.product(cdr3_list, antigen_list, mhc_alleles):
        rows.append({
            "CDR3": cdr3,
            "Antigen": antigen,
            "HLA": hla
        })

    df = pd.DataFrame(rows)
    tmp_file = f"{upload_dir}/pmtnet_input_{uuid.uuid4()}.csv"
    df.to_csv(tmp_file, index=False)

    try:
        object_name = f"inputs/{uuid.uuid4()}.csv"
        return upload_file_to_minio(tmp_file,MINIO_BUCKET,object_name)
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


@tool
async def pMTnet(
                cdr3_list: List[str],
                input_file: str,
                mhc_alleles: Optional[List[str]] = None,
                ) -> str:
    """
    
    pMTnet 是一个用于预测 TCR-pMHC 结合亲和力的工具。
    
    Args:
        支持以下任意输入：
        - cdr3_list
        - input_file：提供fasta文件的肽段。
        - mhc_alleles：对应的 HLA 类型，字符串列表。

    Returns:
    
        异步调用远程 pMTnet 服务接口，获取分析结果。
    
        str: pMTnet 服务返回的 JSON 格式结果
    """
    try:
        input_file_path = prepare_pmtnet_input(
                cdr3_list=cdr3_list,
                input_file=input_file,
                mhc_alleles=mhc_alleles,
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
