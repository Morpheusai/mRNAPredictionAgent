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
    df['Pos'] = pd.to_numeric(df['Pos'], errors='coerce')
    df = df.dropna(subset=['Pos'])
    df['Pos'] = df['Pos'].astype(int)

    # 寻找蛋白质块的分割点（'Pos'列重置为1的位置）
    split_indices = df[df['Pos'] == 1].index.tolist()

    protein_blocks = []
    start_idx = 0
    if not split_indices or split_indices[0] != 0:
        split_indices.insert(0,0)

    for i in range(len(split_indices)):
        start_idx = split_indices[i]
        end_idx = split_indices[i + 1] if i + 1 < len(split_indices) else None
        protein_df = df.iloc[start_idx:end_idx].reset_index(drop=True)
        protein_blocks.append(protein_df)
    
    logger.info(f"Found and split into {len(protein_blocks)} protein blocks from Excel file.")
    return protein_blocks


def _parse_df_to_positions(df):
    """从单个蛋白质的DataFrame中解析positions和identifier"""
    required_columns = ['Pos', 'Aa', 'C']
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in a protein block: {missing_cols}")

    positions = {}
    identifier = "unknown_protein" # 默认标识符
    # 尝试从'Ident'列获取标识符
    if 'Ident' in df.columns and not df['Ident'].empty:
        # 使用第一个有效的标识符
        first_valid_ident = df['Ident'].dropna().iloc[0]
        if first_valid_ident:
            identifier = str(first_valid_ident).strip()


    for _, row in df.iterrows():
        try:
            pos = int(row['Pos'])
            aa = str(row['Aa']).strip()
            c = str(row['C']).strip()
            positions[pos] = (aa, c)
        except (ValueError, TypeError, KeyError):
            # 跳过无法解析的行
            continue

    # logger.info(f"Parsed {len(positions)} positions for protein '{identifier}'.")
    return positions, identifier


def parse_netchop(input_file):
    """解析 NetChop 输出文件（支持 .txt, .tsv, .xlsx 格式）"""
    logger.info(f"Parsing input file: {input_file}")

    if Path(input_file).suffix == '.xlsx':
        # Excel文件现在由多蛋白质解析函数处理
        protein_blocks = _parse_excel_multiple(input_file)
        parsed_data = []
        for block_df in protein_blocks:
            positions, identifier = _parse_df_to_positions(block_df)
            if positions:
                 parsed_data.append({'positions': positions, 'identifier': identifier})
        return parsed_data
    elif Path(input_file).suffix == '.txt' or  Path(input_file).suffix == '.tsv':
        # 文本文件假定为单个蛋白质
        positions = _parse_text(input_file)
        identifier = "protein_from_text_file" # 文本文件没有标识符列，使用默认值
        if positions:
            return [{'positions': positions, 'identifier': identifier}]
        return []
    else:
        raise ValueError("Unsupported file format. Please provide a .txt, .tsv, or .xlsx file.")


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
    # logger.info(f"Built full sequence of length {len(full_sequence)}.")
    return full_sequence

def collect_cut_sites(positions):
    """收集所有剪切位点（C列为S的位置）"""
    cut_sites = [pos for pos in positions if positions[pos][1] == 'S']
    # logger.info(f"Found {len(cut_sites)} cut sites.")
    return cut_sites


def _process_single_site(s_start, full_sequence, cut_sites_set, lengths, max_pos, identifier):
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
            'protein_id': identifier,
            'start': s_start + 1,
            'end': e_pos,
            'length': l,
            'sequence': peptide_seq
        })
    return peptides

def cleavage_peptides(full_sequence, 
                                    cut_sites, 
                                    identifier,
                                    lengths=[8, 9, 10], 
                                    max_workers=min(4, os.cpu_count() or 1)):
    """多线程生成肽段，并去重"""
    # logger.info(f"Generating peptides for protein '{identifier}' using multithreading ({max_workers} workers)...")

    peptides = []
    # 注意：这里的seen_sequences是针对单个蛋白质块内的去重
    seen_sequences = set()
    cut_sites_set = set(cut_sites)
    max_pos = len(full_sequence)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_process_single_site, s_start, full_sequence, cut_sites_set, lengths, max_pos, identifier)
            for s_start in cut_sites
        ]
        for future in as_completed(futures):
            site_peptides = future.result()
            for p in site_peptides:
                seq = p['sequence']
                if seq not in seen_sequences:
                    seen_sequences.add(seq)
                    peptides.append(p)

    # logger.info(f"Generated {len(peptides)} unique peptides for protein '{identifier}'.")
    return peptides


def write_fasta(peptides, output_file):
    with open(output_file, 'w') as f:
        for idx, p in enumerate(peptides, start=1):
            header = f">peptide_{idx} protein|{p['protein_id']}| start{p['start']}_end{p['end']}_len{p['length']}"
            f.write(f"{header}\n{p['sequence']}\n")

def write_csv(peptides, output_file):
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['protein_id', 'start', 'end', 'length', 'sequence'])
        writer.writeheader()
        writer.writerows(peptides)

def write_tsv(peptides, output_file):
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['protein_id', 'start', 'end', 'length', 'sequence'], delimiter='\t')
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
        protein_data_list = parse_netchop(local_input)
        all_peptides = []
        
        # 为去重所有蛋白质的肽段（可选，当前是块内去重）
        all_seen_sequences = set()

        for protein_data in protein_data_list:
            positions = protein_data['positions']
            identifier = protein_data['identifier']
            
            sequence = build_sequence(positions)
            cut_sites = collect_cut_sites(positions)
            
            peptides = cleavage_peptides(
                sequence,
                cut_sites,
                identifier,
                lengths=lengths,
                max_workers=min(4, os.cpu_count() or 1)
            )
            # 全局去重逻辑（如果需要）
            # for p in peptides:
            #    if p['sequence'] not in all_seen_sequences:
            #        all_seen_sequences.add(p['sequence'])
            #        all_peptides.append(p)
            all_peptides.extend(peptides)

        # 按蛋白质ID和起始位置排序
        all_peptides.sort(key=lambda p: (p['protein_id'], p['start']))
        
        # 输出保存
        result_uuid = str(uuid.uuid4())
        object_name = f"{result_uuid}_cleavage_result.{output_format}"
        output_file = Path(output_tmp_dir) / object_name
        if all_peptides:
            write_output(all_peptides, output_file, output_format)
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