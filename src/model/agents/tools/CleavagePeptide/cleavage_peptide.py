import os
import pandas as pd
import csv
import json
import uuid
import asyncio

from dotenv import load_dotenv
from pathlib import Path  
from concurrent.futures import ThreadPoolExecutor, as_completed
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





def parse_netchop(input_file):
    """解析 NetChop 输出文件（支持 .txt, .tsv, .xlsx 格式）"""
    logger.info(f"Parsing input file: {input_file}")

    if Path(input_file).suffix == '.xlsx':
        return _parse_excel(input_file)
    elif Path(input_file).suffix == '.txt' or  Path(input_file).suffix == '.tsv':
        return _parse_text(input_file)
    else:
        raise ValueError("Unsupported file format. Please provide a .txt, .tsv, or .xlsx file.")

def _parse_excel(file_path):
    """解析 Excel 文件"""
    try:
        df = pd.read_excel(file_path, sheet_name=0, header=0)
        df.columns = df.columns.str.strip().str.capitalize()  # 统一列名大小写
    except Exception as e:
        logger.error(f"Failed to read Excel file: {e}")
        raise

    required_columns = ['Pos', 'Aa', 'C']
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in Excel: {missing_cols}")

    positions = {}
    for _, row in df.iterrows():
        try:
            pos = int(row['Pos'])
            aa = str(row['Aa']).strip()
            c = str(row['C']).strip()
            positions[pos] = (aa, c)
        except (ValueError, TypeError, KeyError):
            continue

    logger.info(f"Found {len(positions)} total positions from Excel.")
    return positions

def _parse_text(file_path):
    """解析文本格式文件"""
    positions = {}
    with open(file_path, 'r') as f:
        lines = f.readlines()[1:]  # 跳过第一行表头
        for line in lines:
            if line.lower().startswith('pos') or line.startswith('---'):
                continue
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                pos = int(parts[0])
                aa = parts[1]
                c = parts[2]
                positions[pos] = (aa, c)
            except ValueError:
                continue
    logger.info(f"Found {len(positions)} total positions from text.")
    return positions

def build_sequence(positions):
    """构建完整蛋白质序列"""
    max_pos = max(positions.keys())
    sequence = [''] * max_pos
    for pos in positions:
        sequence[pos - 1] = positions[pos][0]
    full_sequence = ''.join(sequence)
    logger.info(f"Built full sequence of length {len(full_sequence)}.")
    return full_sequence

def collect_cut_sites(positions):
    """收集所有剪切位点（C列为S的位置）"""
    cut_sites = [pos for pos in positions if positions[pos][1] == 'S']
    logger.info(f"Found {len(cut_sites)} cut sites.")
    return cut_sites


def _process_single_site(s_start, full_sequence, cut_sites_set, lengths, max_pos):
    """处理单个剪切位点，生成所有合法肽段"""
    peptides = []
    for l in lengths:
        e_pos = s_start + l
        if e_pos > max_pos:
            continue
        if e_pos not in cut_sites_set:
            continue
        start_idx = s_start
        end_idx = e_pos
        peptide_seq = full_sequence[start_idx:end_idx]
        peptides.append({
            'start': s_start + 1,
            'end': e_pos,
            'length': l,
            'sequence': peptide_seq
        })
    return peptides

def cleavage_peptides(full_sequence, 
                                    cut_sites, 
                                    lengths=[8, 9, 10], 
                                    max_workers=min(4, os.cpu_count() or 1)):
    """多线程生成肽段，并去重"""
    logger.info(f"Generating peptides using multithreading ({max_workers} workers)...")

    peptides = []
    seen_sequences = set()
    cut_sites_set = set(cut_sites)
    max_pos = len(full_sequence)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_process_single_site, s_start, full_sequence, cut_sites_set, lengths, max_pos)
            for s_start in cut_sites
        ]
        for future in as_completed(futures):
            site_peptides = future.result()
            for p in site_peptides:
                seq = p['sequence']
                if seq not in seen_sequences:
                    seen_sequences.add(seq)
                    peptides.append(p)

    logger.info(f"Generated {len(peptides)} unique peptides.")
    return peptides


def write_fasta(peptides, output_file):
    with open(output_file, 'w') as f:
        for idx, p in enumerate(peptides, start=1):
            header = f">peptide_{idx} gi|3333147| start{p['start']}_end{p['end']}_len{p['length']}"
            f.write(f"{header}\n{p['sequence']}\n")

def write_csv(peptides, output_file):
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['start', 'end', 'length', 'sequence'])
        writer.writeheader()
        writer.writerows(peptides)

def write_tsv(peptides, output_file):
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['start', 'end', 'length', 'sequence'], delimiter='\t')
        writer.writeheader()
        writer.writerows(peptides)

def write_json(peptides, output_file):
    with open(output_file, 'w') as f:
        json.dump(peptides, f, indent=2)

def write_output(peptides, output_file, output_format='fasta'):
    if output_format == 'fasta':
        write_fasta(peptides, output_file)
    elif output_format == 'csv':
        write_csv(peptides, output_file)
    elif output_format == 'tsv':
        write_tsv(peptides, output_file)
    elif output_format == 'json':
        write_json(peptides, output_file)
    else:
        raise ValueError(f"Unsupported output format: {output_format}")
    logger.info(f"Output written to {output_file}")


async def run_NetChop_Cleavage(
    input_file: str,
    output_format: str = "fasta",
    lengths=[8, 9, 10],
):
    """
    根据NetChop预测结果文件生成肽段，并输出为指定格式。

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
        positions = parse_netchop(local_input)
        sequence = build_sequence(positions)
        cut_sites = collect_cut_sites(positions)
        peptides = cleavage_peptides(
            sequence,
            cut_sites,
            lengths=lengths,
            max_workers=min(4, os.cpu_count() or 1)
        )
        
        # 输出保存
        result_uuid = str(uuid.uuid4())
        object_name = f"{result_uuid}_cleavage_result.{output_format}"
        output_file = Path(output_tmp_dir) / object_name
        if peptides:
            write_output(peptides, output_file, output_format)
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
def NetChop_Cleavage(input_file: str,
                     output_format: str = "fasta",
                     lengths: list = [8, 9, 10]):
    """
    使用 NetChop 输出结果文件生成切割肽段，支持多格式输出。

    参数：
        input_file (str): MinIO 文件路径，格式如 minio://bucket/file.txt
        output_format (str): 输出格式，支持 fasta, csv, tsv, json
        lengths (list): 要生成的肽段长度列表，默认 [8, 9, 10]
    """
    try:
        return asyncio.run(run_NetChop_Cleavage(
            input_file=input_file,
            output_format=output_format,
            lengths=lengths
        ))
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
        lengths=[8, 9, 10]
    )))