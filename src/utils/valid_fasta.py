import os
import re

from dotenv import load_dotenv
from pathlib import Path
from minio import Minio

from config import CONFIG_YAML
from src.utils.log import logger
load_dotenv()

MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_BUCKET = MINIO_CONFIG["molly_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)


# # 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

def validate_minio_fasta(minio_path):
    """
    验证 MinIO 中的 FASTA 文件格式是否有效
    
    Args:
        minio_path (str): minio://bucket_name/object_path
        
    Returns:
        tuple: (is_valid: bool, error_msg: str)
    """
    
    if not minio_path.startswith("minio://"):
        return False, "路径必须以 minio:// 开头"
    
    try:
        # 解析 bucket 和 object
        path_parts = minio_path[len("minio://"):].split("/", 1)
        if len(path_parts) != 2:
            return False, "路径格式应为 minio://bucket_name/object_path"
        
        bucket_name, object_name = path_parts
        
        # 从 MinIO 读取文件
        try:
            response = minio_client.get_object(bucket_name, object_name)
            content = response.read().decode("utf-8")
        except Exception as e:
            return False, f"读取文件失败: {str(e)}"
        
        # 检查空文件
        if not content.strip():
            return False, "文件内容为空"
        
        lines = content.splitlines()
        has_valid_record = False
        current_header = None
        current_sequence_lines = []  # 存储当前序列的多行内容
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue  # 跳过空行
            
            # Header 行检查
            if line.startswith(">"):
                # 遇到新header时，先处理之前的记录
                if current_header is not None:
                    if not current_sequence_lines:
                        return False, f"记录 {current_header}: header后没有序列"
                    
                    # 合并多行序列并验证
                    full_sequence = ''.join(current_sequence_lines)
                    if not re.match(r'^[A-Za-z*-]+$', full_sequence):
                        return False, f"记录 {current_header}: 序列包含非法字符"
                    
                    has_valid_record = True
                
                # 开始新记录
                current_header = line
                current_sequence_lines = []
            else:
                # 序列行（可能跨越多行）
                if current_header is None:
                    return False, f"行 {line_num}: 缺少header（应以 '>' 开头）"
                current_sequence_lines.append(line)
        
        # 处理最后一个记录
        if current_header is not None:
            if not current_sequence_lines:
                return False, f"记录 {current_header}: header后没有序列"
            
            full_sequence = ''.join(current_sequence_lines)
            if not re.match(r'^[A-Za-z*-]+$', full_sequence):
                return False, f"记录 {current_header}: 序列包含非法字符"
            has_valid_record = True
        
        if not has_valid_record:
            return False, "文件未包含有效的FASTA记录"
        
        return True, "FASTA格式有效"
    
    except Exception as e:
        return False, f"验证过程中发生错误: {str(e)}"