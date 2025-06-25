import os
import pandas as pd
import requests

from minio import Minio
from minio.error import S3Error
from pathlib import Path
from urllib.parse import urlparse

from config import CONFIG_YAML
from src.utils.log import logger

# MinIO 配置
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

output_dir = CONFIG_YAML["TOOL"]["UNIPMT"]["output_tmp_dir"]
os.makedirs(output_dir, exist_ok=True)

def download_file_from_minio(minio_path: str, local_dir: str, local_file_name: str = None):
    try:
        if not minio_path.startswith('minio://'):
            raise ValueError(
                "Invalid MinIO path format. It should start with 'minio://'.")

        url_parts = urlparse(minio_path)
        bucket_name = url_parts.netloc
        object_name = url_parts.path.lstrip('/')

        if not bucket_name or not object_name:
            raise ValueError(
                "Invalid MinIO path format. It should be 'minio://bucket/object'.")

        local_dir_path = Path(local_dir)
        local_dir_path.mkdir(parents=True, exist_ok=True)

        local_file_path = local_dir_path / \
            (local_file_name or Path(object_name).name)

        if local_file_path.exists():
            logger.info(f"File {local_file_path} already exists.")
            return str(local_file_path)

        logger.info(f"Downloading {minio_path} to {local_file_path}...")
        minio_client.fget_object(
            bucket_name, object_name, str(local_file_path))
        logger.info(f"Downloaded {minio_path} to {local_file_path}")
        return str(local_file_path)

    except ValueError as ve:
        logger.error(f"ValueError: {ve}")
        raise
    except S3Error as e:
        logger.info(f"MinIO S3 Error: {e}")
        raise
    except requests.exceptions.ConnectionError:
        logger.info("Connection Error: Failed to connect to MinIO server.")
        raise
    except Exception as e:
        logger.info(f"An unexpected error occurred: {e}")
        raise


def check_minio_connection():
    try:
        minio_client.list_buckets()
        return True
    except S3Error as e:
        print(f"MinIO连接或bucket操作失败: {e}")
        return False

def parse_unipmt_results(minio_path: str) -> str:
    """
    解析 MinIO 上的 UniPMT 结果文件（CSV 格式），返回按 prob 升序排序后的 Markdown 表格。
    若结果超过 7 行，仅返回前 7 行，并附加提示信息。
    """
    if check_minio_connection():
        result_file_path = download_file_from_minio(minio_path, output_dir)

    try:
        # 读取 CSV 文件
        df = pd.read_csv(result_file_path)

        # 过滤掉 label 为 0 的结果
        df_filtered = df[df['label'] == 1]

        # 按 prob 降序排序
        df_sorted = df_filtered.sort_values(by='prob', ascending=False)

        truncated = False
        if len(df_sorted) > 7:
            df_sorted = df_sorted.head(7)
            truncated = True

        # 构建 Markdown 表格
        markdown_lines = [
            "| Peptide | MHC | TCR | prob | label |",
            "|---------|-----|-----|------|-------|"
        ]

        for _, row in df_sorted.iterrows():
            markdown_lines.append(
                f"| {row.get('Peptide', '-')} | {row.get('MHC', '-')} | {row.get('TCR', '-')} | "
                f"{row.get('prob', '-')} | {row.get('label', '-')} |"
            )

        if truncated:
            markdown_lines.append("\n⚠️ 结果超过 7 行，仅显示前 7 行，全部内容请下载表格查看。")

        # 删除临时文件
        file_path = Path(result_file_path)
        file_path.unlink(missing_ok=True)
        logger.info(f"Temporary file {result_file_path} deleted.")

        return "\n".join(markdown_lines)

    except FileNotFoundError:
        logger.error(f"File not found: {result_file_path}")
        return f"File not found: {result_file_path}"
    except pd.errors.EmptyDataError:
        logger.error("The downloaded file is empty.")
        return "The downloaded file is empty."
    except pd.errors.ParserError:
        logger.error("Error parsing the CSV file.")
        return "Error parsing the CSV file."
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return f"An unexpected error occurred: {e}"
    
if __name__ == "__main__":
    test_minio_path = "minio://unipmt-results/cf2cdbc4-3a45-4d16-9ff0-66e8e8789d35_pmt_prediction_result.csv"
    try:
        result = parse_unipmt_results(test_minio_path)
        print(result)
    except Exception as e:
        print(f"Error: {e}")