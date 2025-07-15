import sys
import uuid
import pandas as pd

from pathlib import Path  
from src.utils.log import logger

INPUT_FILENAME = sys.argv[1]
WINDOWS = [8, 9, 10, 11]
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

def write_fasta(peptides, output_file):
    with open(output_file, 'w') as f:
        for tag, peptide in peptides:
            f.write(tag + "\n")
            f.write(peptide + "\n")

# 解析可能包含多个蛋白质块的文件
peptide_datas = parse_netchop(INPUT_FILENAME)
for peptide_data in peptide_datas:
    print(peptide_data)

# 去重复
unique_peptides = []  
unique_fasta_items = []  
for tag, peptide in peptide_datas:
    if peptide not in unique_peptides:
        unique_peptides.append(peptide)
        unique_fasta_items.append((tag, peptide))

# 输出保存
result_uuid = str(uuid.uuid4())
output_file = f"./{result_uuid}_cleavage_result.fasta"
if unique_fasta_items:
    write_fasta(unique_fasta_items, output_file)
else:
    logger.warning("No valid peptides generated.")
