import os
import uuid
import sys

from dotenv import load_dotenv
from pathlib import Path
from minio import Minio
from minio.error import S3Error


load_dotenv()
current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML



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

def upload_file_to_minio(
    local_file_path: str,
    bucket_name: str,
    minio_object_name: str = None,
) -> str:
    """
    上传本地文件到MinIO存储
    
    Args:
        minio_client: 已初始化的MinIO客户端实例
        local_file_path: 本地文件路径
        bucket_name: MinIO桶名称
        minio_object_name: 在MinIO中存储的文件名(可选)，如果不指定则使用随机UUID+原文件名
        
    Returns:
        str: MinIO访问地址 (格式: minio://bucket/object_name)
        
    Raises:
        FileNotFoundError: 如果本地文件不存在
        S3Error: MinIO操作相关的错误
    """
    # 检查本地文件是否存在
    local_path = Path(local_file_path)
    if not local_path.exists():
        raise FileNotFoundError(f"本地文件不存在: {local_file_path}")
    
    # 如果没有指定MinIO中的文件名，则生成一个
    if minio_object_name is None:
        file_ext = local_path.suffix  # 获取文件扩展名
        minio_object_name = f"{uuid.uuid4().hex}{file_ext}"
    
    try:
        # 确保桶存在
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        
        # 上传文件
        minio_client.fput_object(
            bucket_name,
            minio_object_name,
            str(local_path)
        )
        
        # 返回MinIO地址
        return f"minio://{bucket_name}/{minio_object_name}"
        
    except S3Error as e:
        raise S3Error(f"上传文件到MinIO失败: {e}") from e


# # 上传文件
# try:

#     print(MINIO_ENDPOINT)
#     print(MINIO_ACCESS_KEY)
#     print(MINIO_SECRET_KEY)
#     print(MINIO_BUCKET)
#     print(MINIO_SECURE)

#     url = upload_file_to_minio(
#         local_file_path="39613742.pdf",
#         bucket_name= MINIO_BUCKET,
#     )
#     print(f"文件访问URL: {url}")
# except Exception as e:
#     print(f"上传失败: {e}")        