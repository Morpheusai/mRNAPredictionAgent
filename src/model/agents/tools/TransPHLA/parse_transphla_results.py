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

output_dir = CONFIG_YAML["TOOL"]["TRANSPHLA"]["output_tmp_dir"]
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

def parse_transphla_results(minio_path: str) -> str:
    """
    解析 MinIO 上的 TransPHLA 预测结果 CSV 文件，返回 Markdown 表格（最多显示前 7 个预测为 binder 的条目）。
    """
    if check_minio_connection():
        result_file_path = download_file_from_minio(minio_path, output_dir)

    try:
        # 读取 CSV 文件
        df = pd.read_csv(result_file_path)

        # # 仅保留预测为 binder（y_pred == 1）的条目
        # df_binders = df[df['y_pred'] == 1].copy()

        # if df_binders.empty:
        #     return "❗ 没有预测为 binder 的肽段。"

        # 按 y_prob 降序排序所有结果
        df_sorted = df.sort_values(by='y_prob', ascending=False)

        truncated = False
        if len(df_sorted) > 7:
            df_sorted = df_sorted.head(7)
            truncated = True

        # 构建 Markdown 表格
        markdown_lines = [
            "| HLA | HLA_sequence | Peptide | y_pred | y_prob |",
            "|-----|---------------|---------|--------|--------|"
        ]

        for _, row in df_sorted.iterrows():
            markdown_lines.append(
                f"| {row['HLA']} | {row['HLA_sequence']} | {row['peptide']} | {row['y_pred']} | {row['y_prob']:.4f} |"
            )

        if truncated:
            markdown_lines.append("\n⚠️ 结果超过 7 行，仅显示前 7 行，全部内容请下载原始表格查看。")

        # 删除临时文件
        Path(result_file_path).unlink(missing_ok=True)
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
