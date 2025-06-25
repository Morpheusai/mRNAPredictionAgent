import asyncio
import json
import uuid

from pathlib import Path
from langchain_core.tools import tool

 
from config import CONFIG_YAML
from src.utils.log import logger
from src.utils.minio_utils import upload_file_to_minio

TMP_OUTPUT_DIR = CONFIG_YAML["TOOL"]["EXTRACT_PEPTIDE"]["tmp_extract_peptide_dir"]
tmp_output_dir = Path(TMP_OUTPUT_DIR)
tmp_output_dir.mkdir(parents=True, exist_ok=True)

# 配置环境变量和 MinIO 连接
MINIO_BUCKET = CONFIG_YAML["MINIO"]["extract_peptide_bucket"]


def validate_peptide_sequence(peptide: str) -> bool:
    """
    验证肽段序列是否仅包含合法的20种氨基酸（大写单字母）。
    忽略大小写和多余空格，空字符串视为无效。
    """
    valid_amino_acids = set("ACDEFGHIKLMNPQRSTVWY")
    cleaned = peptide.strip().upper()
    if not cleaned:
        return False
    return all(aa in valid_amino_acids for aa in cleaned)

def write_multiple_peptides_to_fasta(peptides: list[str], output_path: Path) -> bool:
    """将多个肽段序列写入fasta文件"""
    try:
        with open(output_path, 'w') as f:
            for i, seq in enumerate(peptides, 1):
                seq = seq.strip().upper()
                if not validate_peptide_sequence(seq):
                    raise ValueError(f"无效氨基酸序列：{seq}")
                f.write(f">peptide_{i}\n{seq}\n")
        return True
    except Exception as e:
        logger.error(f"写入多肽段 FASTA 文件失败: {e}")
        return False

async def process_multiple_peptides(peptide_list: list[str]) -> str:
    """
    接收多条肽段，验证合法性后写入一个 FASTA 文件并上传到 MinIO。
    """
    clean_peptides = []
    # 验证肽段序列
    for i, pep in enumerate(peptide_list, 1):
        seq = pep.strip().upper()
        if not validate_peptide_sequence(seq):
            return json.dumps({
                "type": "text",
                "content": f"第 {i} 条肽段非法：{pep}，请确认仅包含标准氨基酸（ACDEFGHIKLMNPQRSTVWY）",
            }, ensure_ascii=False)
        clean_peptides.append(seq)

    # 保存为fasta文件
    file_id = uuid.uuid4().hex
    object_name = f"{file_id}_peptide_sequence.fasta"
    fasta_file_tmp_path = tmp_output_dir / object_name
    try:
        with open(fasta_file_tmp_path, 'w') as f:
            for idx, seq in enumerate(clean_peptides, 1):
                f.write(f">peptide_{idx}\n{seq}\n")
    except Exception as e:
        return json.dumps({
            "type": "text",
            "content": f"写入 FASTA 文件失败: {e}",
        }, ensure_ascii=False)
    # 上传到MinIO

    file_path = upload_file_to_minio(str(fasta_file_tmp_path),MINIO_BUCKET,object_name)
    try:
        fasta_file_tmp_path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"临时文件删除失败: {e}")  
    return json.dumps({
        "type": "link",
        "url": file_path,
        "content": f"肽段序列已写入fas文件成功",
    }, ensure_ascii=False)

@tool
def ExtractPeptides(peptide_list: list[str]) -> str:
    """
    将多个肽段序列写入一个 fasta 文件，并上传至 MinIO。
    Args:
        peptide_list: 多条肽段（字符串）组成的列表。
    Returns:
        JSON 字符串，包含 MinIO 地址或错误信息
    """
    try:
        return asyncio.run(process_multiple_peptides(peptide_list))
    except Exception as e:
        result = {
                "type": "text",
                "content": f"调用ExtractPeptide工具失败: {e}"
            }
        return json.dumps(result, ensure_ascii=False)
    
if __name__ == "__main__":
    
    # 测试代码
    peptide_list = ["MNDTEAI", "LLGQVGR", "SPTYSLK"]
    result = asyncio.run(process_multiple_peptides(peptide_list))
    print(result)