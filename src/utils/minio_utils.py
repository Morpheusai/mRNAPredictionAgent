import os
import uuid
import sys
import tempfile

from dotenv import load_dotenv
from pathlib import Path
from minio import Minio
from minio.error import S3Error
from urllib.parse import urlparse


load_dotenv()
current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML
from src.utils.log import logger


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
        logger.info(f"MinIO path: minio://{bucket_name}/{minio_object_name}")
        # 返回MinIO地址
        return f"minio://{bucket_name}/{minio_object_name}"
        
    except S3Error as e:
        logger.error(f"MinIO S3 Error: {e}")
        raise S3Error(f"上传文件到MinIO失败: {e}") from e
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise
        






def download_from_minio_uri(uri: str, local_path: str = None) -> str:
    """
    通过MinIO路径下载文件
    
    Args:
        uri: MinIO路径 (格式: minio://bucket-name/path/to/object)
        local_path: (可选)本地保存路径（可以是目录或完整路径）
                   - 如果是目录：自动使用原文件名（前面加UUID）
                   - 如果未指定：使用临时目录+UUID_原文件名
    
    Returns:
        str: 下载文件的完整本地路径（包含文件名）
    
    Raises:
        ValueError: 无效的URI格式
        S3Error: MinIO操作错误
        IOError: 本地文件错误
    """
    # 解析URI
    parsed = urlparse(uri)
    if parsed.scheme != 'minio':
        raise ValueError("无效的MinIO URI，必须以 minio:// 开头")
    
    bucket_name = parsed.netloc
    object_name = parsed.path.lstrip('/')
    original_filename = os.path.basename(object_name)
    
    # 生成带UUID的新文件名
    filename_with_uuid = f"{uuid.uuid4()}_{original_filename}"

    # 处理本地路径
    if local_path is None:
        # 默认使用临时目录+UUID_原文件名
        local_path = os.path.join(tempfile.gettempdir(), filename_with_uuid)
    elif os.path.isdir(local_path):
        # 如果提供的是目录，自动添加UUID_原文件名
        local_path = os.path.join(local_path, filename_with_uuid)
    else:
        # 如果提供的是完整路径，直接使用（但不加UUID，因为用户可能想要自定义文件名）
        pass  # 保持原样
    
    # 确保目录存在
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    # 执行下载
    minio_client.fget_object(
        bucket_name=bucket_name,
        object_name=object_name,
        file_path=local_path
    )
    
    # 返回绝对路径
    return os.path.abspath(local_path)

download_from_minio_uri("minio://molly/29959599-2e39-4a66-a22d-ccfb86dedd21_hlas.fasta","/mnt/workspace/dev/ltc/mRNAPredictionAgent/src/utils")
