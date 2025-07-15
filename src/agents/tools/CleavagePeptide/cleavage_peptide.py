import os
import pandas as pd
import json
import uuid
import asyncio

from dotenv import load_dotenv
from pathlib import Path  
from langchain_core.tools import tool

from src.utils.minio_utils import upload_file_to_minio,download_from_minio_uri
from src.utils.log import logger
from config import CONFIG_YAML
load_dotenv()

input_tmp_dir = CONFIG_YAML["TOOL"]["NETCHOP_CLEAVAGE"]["input_tmp_dir"]
output_tmp_dir = CONFIG_YAML["TOOL"]["NETCHOP_CLEAVAGE"]["output_tmp_dir"]
os.makedirs(input_tmp_dir, exist_ok=True)
os.makedirs(output_tmp_dir, exist_ok=True)

MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_BUCKET = CONFIG_YAML["MINIO"]["netchop_cleavage_bucket"]

def write_fasta(peptides, output_file):
    with open(output_file, 'w') as f:
        for tag, peptide in enumerate(peptides):
            f.write(tag + "\n")
            f.write(peptide + "\n")

def _parse_excel_multiple(file_path):
    """
    解析包含多个蛋白质块的Excel文件。
    通过检测'Pos'列是否重置为1来分割蛋白质块。
    """
    try:
        df = pd.read_excel(file_path, header=0)
        # 预处理列名，去除首尾空格并统一大写开头
        df.columns = df.columns.str.strip().str.capitalize()
    except Exception as e:
        logger.error(f"Failed to read Excel file: {e}")
        raise

    # 过滤掉非数据行（例如摘要行），这些行的'Pos'列通常无法转换为数字
    df['Pos'] = pd.to_numeric(df['Pos'], errors='coerce').astype('Int64')

    # 寻找蛋白质块的分割点（'Pos'列重置为1的位置）
    split_indices = df[df['Pos'] == 1].index.tolist()
    len_splits = len(split_indices)
    split_indices.append(len(df))

    protein_blocks = []
    start_idx = 0
     
    for i in range(len_splits):
        start_idx = split_indices[i]
        end_idx = split_indices[i + 1] - 1
        protein_df = df.iloc[start_idx:end_idx].reset_index(drop=True)
        protein_blocks.append(protein_df)
    
    logger.info(f"Found and split into {len(protein_blocks)} protein blocks from Excel file.")
    return protein_blocks

def parse_netchop(input_file, WINDOWS = [8, 9, 10, 11]):
    """解析 NetChop 输出文件（支持 .txt, .tsv, .xlsx 格式）"""
    logger.info(f"Parsing input file: {input_file}")

    if Path(input_file).suffix == '.xlsx':
        # Excel文件现在由多蛋白质解析函数处理
        protein_blocks = _parse_excel_multiple(input_file)
        parsed_peptide_data = []
        for block_df in protein_blocks:
            len_block_df = len(block_df)
            for window in WINDOWS:
                if window <= len_block_df:
                    tag = ">" + block_df.iloc[0]['Ident']
                    origin_peptide = "".join(block_df["Aa"])
                    parsed_peptide_data.append((tag, origin_peptide)) # 会重复推入，之后一定要去重
                    # 考虑长片段的切
                    len_diff = len_block_df - window
                    if len_diff == 0:
                        continue
                    for i in range(len_diff + 1):
                        start_idx = i
                        end_idx = i + window
                        flag_start = False
                        flag_end = False
                        if start_idx == 0 or block_df.iloc[start_idx-1]["C"] == "S":
                            flag_start = True
                        if end_idx == len_block_df or block_df.iloc[end_idx-1]["C"] == "S":
                            flag_end = True
                        if flag_start and flag_end:
                            tag = ">" + block_df.iloc[0]['Ident'] + "-" + str(window) + "-" + str(start_idx) + "-" + str(end_idx-1)
                            content = origin_peptide[start_idx: end_idx]
                            parsed_peptide_data.append((tag, content))
        return parsed_peptide_data
    else:
        raise ValueError("Unsupported file format. Please provide a .fasta file.")

async def run_NetChop_Cleavage(
    input_file: str,
    output_format: str = "fasta",
    lengths=[8, 9, 10, 11],
):
    """
    根据NetChop预测结果文件生成肽段，并输出为指定格式。
    支持包含多个蛋白质块的Excel文件。

    参数：
        input_file (str): 输入文件路径 (.txt, .tsv, .xlsx)
        lengths (list): 要提取的肽段长度，默认 [8,9,10]
        output_format (str): 输出格式，支持 ['fasta', 'csv', 'tsv', 'json']
    """

    logger.info(f"Starting peptide generation from {input_file}...")
    local_input = download_from_minio_uri(input_file, input_tmp_dir)
    suffix = Path(local_input).suffix.lower()
    if suffix not in [".txt", ".tsv" ,".xlsx"]:
        return json.dumps({"type": "text", 
                            "content": "仅支持 txt 、 tsv 文件 或 excel文件 "
                            }, ensure_ascii=False)
    try:
        # 解析可能包含多个蛋白质块的文件
        peptide_datas = parse_netchop(local_input, lengths)

        # 去重复
        unique_peptides = []  
        unique_fasta_items = []  
        for tag, peptide in peptide_datas:
            if peptide not in unique_peptides:
                unique_peptides.append(peptide)
                unique_fasta_items.append((tag, peptide))

        # 输出保存
        result_uuid = str(uuid.uuid4())
        object_name = f"{result_uuid}_cleavage_result.{output_format}"
        output_file = Path(output_tmp_dir) / object_name
        if unique_fasta_items:
            write_fasta(unique_fasta_items, output_file)
        else:
            logger.warning("No valid peptides generated.")
        
        file_path = upload_file_to_minio(str(output_file),MINIO_BUCKET,str(object_name))
        os.remove(local_input)
        os.remove(output_file)
        
        return json.dumps({
            "type": "link",
            "url": file_path,
            "content": "已完成切割，请查看内容"
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"NetChop 后处理失败: {e}")
        return json.dumps({
            "type": "text",
            "content": f"NetChop_Cleavage 处理失败: {e}"
        }, ensure_ascii=False)
@tool
def NetChop_Cleavage(
    input_file: str,
    output_format: str = "fasta",
    lengths: list = [8, 9, 10, 11]
):
    """
    使用 NetChop 输出结果文件生成切割肽段，支持多格式输出。

    参数：
        input_file (str): MinIO 文件路径，格式如 minio://bucket/file.txt
        output_format (str): 输出格式，支持 fasta, csv, tsv, json
        lengths (list): 要生成的肽段长度列表，默认 [8, 9, 10, 11]
    """
    try:
        # 如果传入的是 [-1]，则使用默认的长度列表
        if lengths == [-1]:
            lengths = [8, 9, 10, 11]
            
        return asyncio.run(
            run_NetChop_Cleavage(
                input_file=input_file,
                output_format=output_format,
                lengths=lengths
            )
        )
    except Exception as e:
        return json.dumps({
            "type": "text",
            "content": f"NetChop_Cleavage 执行失败: {e}"
        }, ensure_ascii=False)

# 示例运行
if __name__ == "__main__":
    print(asyncio.run(run_NetChop_Cleavage(
        input_file="minio://netchop-results/b8bb68b2f0d14d128228e66724f4bf60_NetChop_results.xlsx",
        output_format="fasta",
        lengths=[8, 9, 10, 11]
    )))