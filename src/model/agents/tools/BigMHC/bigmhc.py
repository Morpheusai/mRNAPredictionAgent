import aiohttp
import asyncio
import json
import os
import pandas as pd
import re
import sys
import tempfile
import traceback
import uuid

from dotenv import load_dotenv
from langchain_core.tools import tool
from minio import Minio
from minio.error import S3Error
from pathlib import Path
from typing import List, Union, Optional

from utils.minio_utils import upload_file_to_minio,download_from_minio_uri
current_file = Path(__file__).resolve()
project_root = current_file.parents[5]                
sys.path.append(str(project_root))
from config import CONFIG_YAML
load_dotenv()

bigmhc_url = CONFIG_YAML["TOOL"]["BIGMHC"]["url"]

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_BUCKET = MINIO_CONFIG["bigmhc_bucket"]


def parse_fasta(filepath: str) -> List[str]:
    peptides = []
    with open(filepath, "r") as f:
        current = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current:
                    peptides.append("".join(current))
                    current = []
            else:
                current.append(line)
        if current:
            peptides.append("".join(current))
    return peptides

#  下载并解析 MinIO 文件
def resolve_minio_to_list(minio_path: str, is_peptide: bool = False) -> List[str]:

    path = minio_path[len("minio://"):]
    bucket, object_path = path.split("/", 1)

    ext = os.path.splitext(object_path)[1].lower()

    with tempfile.NamedTemporaryFile(delete=True) as tmp:
        download_from_minio_uri(minio_path,tmp.name)

        if is_peptide and ext in [".fa", ".fasta", ".fas"]:
            return parse_fasta(tmp.name)
        else:
            return [line.strip() for line in open(tmp.name) if line.strip()]


#  支持 list[str] 或 minio:// 路径
def resolve_input(input_val: Union[str, List[str]], is_peptide: bool = False) -> List[str]:
    if isinstance(input_val, list):
        return [line.strip() for line in input_val if line.strip()]
    elif isinstance(input_val, str) and input_val.startswith("minio://"):
        return resolve_minio_to_list(input_val, is_peptide=is_peptide)
    else:
        raise ValueError("必须是列表或以 minio:// 开头的字符串")

#  前处理 + 上传 MinIO，返回 minio 路径
def generate_bigmhc_input_file(
    input_file: Union[List[str], str],
    mhc_alleles: List[str],
    default_tgt: int = 1
) -> str:
    peptides = resolve_input(input_file, is_peptide=True)
    hlas = resolve_input(mhc_alleles)

    if not peptides or not hlas:
        raise ValueError("肽段或 HLA 输入不能为空")

    if len(peptides) == len(hlas):
        data = [{"mhc": hla.strip(), "pep": pep.strip(), "tgt": default_tgt}
                for pep, hla in zip(peptides, hlas)]
    else:
        data = [{"mhc": hla.strip(), "pep": pep.strip(), "tgt": default_tgt}
                for hla in hlas for pep in peptides]

    df = pd.DataFrame(data, columns=["mhc", "pep", "tgt"])

    # 创建临时文件
    with tempfile.NamedTemporaryFile(delete=True, suffix=".csv") as tmp:
        df.to_csv(tmp.name, index=False)
        unique_name = f"{uuid.uuid4().hex}_bigmhc_el_input.csv"
        minio_upload_path = upload_file_to_minio(tmp.name,MINIO_BUCKET,unique_name)
    return minio_upload_path

# def generate_bigmhc_im_input_from_fasta(
#     fasta_minio_path: str,
#     default_tgt: int = 1
# ) -> str:
#     """
#     解析 >peptide|HLA 格式的 FASTA 文件，并生成符合 BigMHC-IM 的 CSV（自动补全 HLA- 前缀）。

#     参数:
#     - fasta_minio_path: MinIO 路径，例如 minio://bucket/file.fasta
#     - default_tgt: 默认标签，通常为 1

#     返回:
#     - minio:// 路径的 CSV 文件
#     """
#     local_path = tempfile.NamedTemporaryFile(delete=True).name
#     download_from_minio_uri(fasta_minio_path,local_path)

#     records = []
#     HLA_REGEX = re.compile(r"^(HLA-)?[ABC]\*\d{2}:\d{2}$")

#     with open(local_path, "r") as f:
#         current_hla = ""
#         for line in f:
#             line = line.strip()
#             if line.startswith(">") and "|" in line:
#                 parts = line[1:].split("|", 1)
#                 if len(parts) == 2 and HLA_REGEX.fullmatch(parts[1].strip()):
#                     hla = parts[1].strip()
#                     if not hla.startswith("HLA-"):
#                         hla = "HLA-" + hla
#                     current_hla = hla
#             elif line and current_hla:
#                 pep_seq = line.strip()
#                 records.append({
#                     "mhc": current_hla,
#                     "pep": pep_seq,
#                     "tgt": default_tgt
#                 })
#                 current_hla = ""  # reset for next

#     if not records:
#         raise ValueError("未能从 FASTA 中解析出合法的 >peptide|HLA 项")

#     df = pd.DataFrame(records, columns=["mhc", "pep", "tgt"])
#     with tempfile.NamedTemporaryFile(delete=True, suffix=".csv") as tmp:
#         df.to_csv(tmp.name, index=False)
#         unique_name = f"{uuid.uuid4().hex}_bigmhc_im_input.csv"
#         minio_upload_path = upload_file_to_minio(tmp.name,MINIO_BUCKET,unique_name)
#     return minio_upload_path

# def prepare_bigmhc_input_file(
#     input_file: Optional[str],
#     peptide_input: Optional[Union[List[str], str]],
#     hla_input: Optional[Union[List[str], str]]
# ) -> str:
#     if input_file:
#         if peptide_input or hla_input:
#             raise ValueError("不允许同时提供 input_file 和 peptide/hla 参数")
#         return input_file

#     if peptide_input and hla_input:
#         return generate_bigmhc_input_file(peptide_input, hla_input)

#     raise ValueError("请提供 input_file，或同时提供 peptide_input 和 hla_input")

def prepare_bigmhc_input_file(
    input_file: str,
    mhc_alleles: List[str],
) -> str:
    # if input_file:
    #     if peptide_input or hla_input:
    #         raise ValueError("不允许同时提供 input_file 和 peptide/hla 参数")

    #     # 判断是否是 fasta 文件（用于 BigMHC_IM 特殊格式）
    #     if input_file.startswith("minio://") and input_file.lower().endswith((".fa", ".fasta", ".fsa")):
    #         from tempfile import NamedTemporaryFile
    #         import re

    #         # 支持 HLA-A*02:01 和 A*02:01 等形式
    #         HLA_REGEX = re.compile(r"^(HLA-)?[ABC]\*\d{2}:\d{2}$")


    #         with NamedTemporaryFile(delete=True) as tmp:
    #             download_from_minio_uri(input_file,tmp.name)

    #             with open(tmp.name, "r") as f:
    #                 for line in f:
    #                     if line.startswith(">") and "|" in line:
    #                         parts = line[1:].split("|", 1)
    #                         if len(parts) == 2 and HLA_REGEX.fullmatch(parts[1].strip()):
    #                             return generate_bigmhc_im_input_from_fasta(input_file)

    #     return input_file  # 普通 .csv 文件

    if input_file and mhc_alleles:
        return generate_bigmhc_input_file(input_file, mhc_alleles)

    raise ValueError("请提供 input_file，或同时提供 peptide_input 和 hla_input")


@tool
async def BigMHC_EL(
    input_file: str,
    mhc_alleles: Optional[List[str]] = None,
    ) -> str:
    """
        BigMHC-EL：用于 MHC-I 表位肽段的抗原递呈预测。
        参数说明：
        - input_file：提供fasta文件的肽段。
        - mhc_alleles：对应的 HLA 类型，字符串列表。


        返回值：
        - JSON 字符串，包含预测结果或错误信息。
    """
    try:
        try:
            input_file = prepare_bigmhc_input_file(input_file,  mhc_alleles)
        except ValueError as ve:
            return json.dumps({
                "type": "text",
                "content": f" 参数错误: {str(ve)}"
            }, ensure_ascii=False)

        payload = {
            "input_file": input_file,
            "model_type": "el"
        }

        timeout = aiohttp.ClientTimeout(total=60)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(bigmhc_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()
        return json.dumps({
            "type": "text",
            "content": f" BigMHC-EL 预测失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)


@tool
async def BigMHC_IM(
    input_file: str,
    mhc_alleles: Optional[List[str]] = None,
) -> str:
    """
        BigMHC-IM：用于 MHC-I 肽段的免疫原性（Immunogenicity）预测。

        参数说明：
        - input_file：提供fasta文件的肽段。
        - mhc_alleles：对应的 HLA 类型，字符串列表。

        返回值：
        - JSON 字符串，包含模型预测结果或错误信息。
    """
    try:
        try:
            input_file = prepare_bigmhc_input_file(input_file, mhc_alleles)
        except ValueError as ve:
            return json.dumps({
                "type": "text",
                "content": f" 参数错误: {str(ve)}"
            }, ensure_ascii=False)

        payload = {
            "input_file": input_file,
            "model_type": "im" 
        }

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(bigmhc_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()

    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f" BigMHC-IM 预测失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)

if __name__ == "__main__":
    # async def BigMHC_EL_test():
    #     result = await BigMHC_EL.ainvoke({
    #         "input_file": "minio://molly/9e221df5-1b61-40ff-bb00-699e1c7d7dfc_bigmhc_example1.csv",
    #     })
    #     print("BigMHC_EL 异步调用结果：")
    #     print(result)

    # asyncio.run(BigMHC_EL_test())
    # async def test_bigmhc_el():
    #     #  传入 FASTA 文件的 MinIO 路径（请替换为你的真实路径）
    #     peptide_fasta_minio_path = "minio://netchop-cleavage-results/d05f77be-a871-4097-bbe3-cf1e1effcec4_cleavage_result.fasta"

    #     # HLA 等位基因列表（一个或多个）
    #     hla_list = ["HLA-A*02:01", "HLA-B*07:02"]

    #     # 调用工具进行预测
    #     result = await BigMHC_EL.ainvoke({
    #         "peptide_input": peptide_fasta_minio_path,
    #         "hla_input": hla_list
    #     })

    #     print("=== BigMHC_EL 测试结果 ===")
    #     print(result)

    # asyncio.run(test_bigmhc_el())
    async def BigMHC_IM_test():
        result = await BigMHC_IM.ainvoke({
            # "input_file": "minio://molly/9e221df5-1b61-40ff-bb00-699e1c7d7dfc_bigmhc_example1.csv",
            "input_file": "minio://molly/da861418-bdac-43b3-8760-853d8140ab37_bigmhc_el.fasta",#特殊形式的fasta文件
            
        })
        print("BigMHC_IM 异步调用结果：")
        print(result)

    asyncio.run(BigMHC_IM_test())
    # async def test_bigmhc_im():
    #     # 传入 FASTA 文件的 MinIO 路径（请替换为你的真实路径）
    #     peptide_fasta_minio_path = "minio://netchop-cleavage-results/d05f77be-a871-4097-bbe3-cf1e1effcec4_cleavage_result.fasta"

    #     #  HLA 等位基因列表（一个或多个）
    #     hla_list = ["HLA-A*02:01", "HLA-B*07:02"]

    #     # 调用工具进行预测
    #     result = await BigMHC_EL.ainvoke({
    #         "peptide_input": peptide_fasta_minio_path,
    #         "hla_input": hla_list
    #     })

    #     print("=== BigMHC_EL 测试结果 ===")
    #     print(result)

    # asyncio.run(test_bigmhc_im())
