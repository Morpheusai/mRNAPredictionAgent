import asyncio
import json
import os
import sys
import uuid

from pathlib import Path
from minio import Minio
from minio.error import S3Error
from langchain_core.tools import tool

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]  # 向上回溯 4 层目录：src/model/agents/tools → src/model/agents → src/model → src → 项目根目录
sys.path.append(str(project_root))    # 将项目根目录添加到 sys.path
from config import CONFIG_YAML
from src.utils.log import logger
TMP_OUTPUT_DIR = CONFIG_YAML["TOOL"]["EXTRACT_PEPTIDE"]["tmp_extract_peptide_dir"]
tmp_output_dir = Path(TMP_OUTPUT_DIR)
tmp_output_dir.mkdir(parents=True, exist_ok=True)
# 配置环境变量和 MinIO 连接
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_ENDPOINT = CONFIG_YAML["MINIO"]["endpoint"]
MINIO_BUCKET = CONFIG_YAML["MINIO"]["extract_peptide_bucket"]
MINIO_SECURE = CONFIG_YAML["MINIO"].get("secure", False)

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

def check_minio_connection(bucket_name=MINIO_BUCKET):
    try:
        minio_client.list_buckets()
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        return True
    except S3Error as e:
        print(f"MinIO连接或bucket操作失败: {e}")
        return False

def upload_to_minio(file_path: str, output_filename: str):
    try:
        minio_client.fput_object(
            MINIO_BUCKET,
            output_filename,
            file_path
        )
        return f"minio://{MINIO_BUCKET}/{output_filename}", None
    except S3Error as e:
        return None, f"上传 MinIO 失败: {e}"

def validate_peptide_sequence(peptide: str) -> bool:
    """验证肽段序列是否包含合法的氨基酸"""
    valid_amino_acids = set("ACDEFGHIKLMNPQRSTVWY")
    return all(aa in valid_amino_acids for aa in peptide)

def write_fasta(peptide_sequence: str, output_path: Path) -> bool:
    """将肽段序列写入fasta文件"""
    try:
        with open(output_path, 'w') as f:
            # f.write(f">peptide_sequence_{uuid.uuid4().hex}\n")
            f.write(f">peptide_sequence\n")
            f.write(peptide_sequence)
            # for i, peptide in enumerate(peptide_sequence, 1):
            #     f.write(f">peptide_{i}\n")
            #     f.write(f"{peptide}\n")
        return True
    except Exception as e:
        logger.error(f"写入fasta文件失败: {e}")
        # print(f"写入fasta文件失败: {e}")
        return False

async def process_peptide_sequence(peptide_sequence: str) -> str:
    """处理肽段序列，包括验证、写入fasta文件并上传到MinIO"""
    
    # 验证肽段序列
    if not validate_peptide_sequence(peptide_sequence):
        return json.dumps({
            "type": "text",
            "content": "输入的肽段序列包含无效的氨基酸，请检查并重试。",
        }, ensure_ascii=False)

    # 保存为fasta文件
    file_id = uuid.uuid4().hex
    object_name = f"{file_id}_peptide_sequence.fasta"
    fasta_file_tmp_path = tmp_output_dir / object_name
    if not write_fasta(peptide_sequence, fasta_file_tmp_path):
        return json.dumps({
            "type": "text",
            "content": "无法生成fasta文件。",
        }, ensure_ascii=False)

    # 上传到MinIO
    minio_available = check_minio_connection()
    if minio_available:
        file_path, error = upload_to_minio(str(fasta_file_tmp_path), object_name)
        if error:
            return json.dumps({
                "type": "text",
                "content": f"上传MinIO失败: {error}",
            }, ensure_ascii=False)
        else:
            try:
                fasta_file_tmp_path.unlink(missing_ok=True)
            except Exception as e:
                return json.dumps({
                    "type": "text",
                    "content": f"删除临时文件失败: {e}",
                }, ensure_ascii=False)
        return json.dumps({
            "type": "link",
            "url": file_path,
            "content": f"肽段序列已写入fas文件成功",
        }, ensure_ascii=False)
    else:
        return json.dumps({
            "type": "text",
            "content": "MinIO连接失败。",
        }, ensure_ascii=False)

@tool
def ExtractPeptide(peptide_sequence: str) -> str:
    """
    提取肽段序列并生成fasta文件，上传到MinIO
    Args:
        peptide_sequence: 肽段序列
    Returns:
        str: 返回结果的JSON字符串
    """
    try:
        return asyncio.run(process_peptide_sequence(peptide_sequence))
    except Exception as e:
        result = {
                "type": "text",
                "content": f"调用ExtractPeptide工具失败: {e}"
            }
        return json.dumps(result, ensure_ascii=False)