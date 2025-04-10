import asyncio
import json
import subprocess
import sys
import os
import requests

from minio import Minio
from minio.error import S3Error
from pathlib import Path
from langchain_core.tools import tool
from urllib.parse import urlparse

current_file = Path(__file__).resolve()
current_script_dir = current_file.parent
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from src.utils.log import logger
from src.model.agents.tools.piste_Tool.parse_piste_result import parse_piste_result
from config import CONFIG_YAML

# PISTE 相关路径配置
piste_predict = current_script_dir / "piste_predict.py"
piste_env_python = CONFIG_YAML["TOOL"]["PISTE"]["piste_env_python_dir"]
input_tmp_dir = CONFIG_YAML["TOOL"]["PISTE"]["input_tmp_piste_dir"]
output_dir = CONFIG_YAML["TOOL"]["PISTE"]["output_tmp_piste_dir"]
os.makedirs(input_tmp_dir, exist_ok=True)
os.makedirs(output_dir, exist_ok=True)
# ---------
# input_file = "/mnt/softwares/PISTE/demo/example.csv"
# piste_predict = Path(__file__).parent / "piste_predict.py"
# piste_env_python = "/mnt/softwares/miniconda3/envs/piste/bin/python"
# output_dir = "/mnt/softwares/PISTE/demo"
# ---------

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


async def run_PISTE(input_file_dir_minio: str,
                    model_name=None,
                    threshold=None,
                    antigen_type=None):
    if check_minio_connection():
        input_file = download_file_from_minio(input_file_dir_minio, input_tmp_dir)
    if not input_file:
        raise FileNotFoundError("Input file not found.")
    command = [
        piste_env_python,
        piste_predict,
        "--input", input_file,
        "--output", output_dir
    ]

    # 可选参数
    if model_name:
        command += ["--model_name", model_name]
    if threshold:
        command += ["--threshold", str(threshold)]
    if antigen_type:
        command += ["--antigen_type", antigen_type]

    try:
        process = await asyncio.create_subprocess_exec(
            *map(str, command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        stdout, stderr = await process.communicate()
        # print(f"[STDOUT]\n{stdout.decode()}")
        # print(f"[STDERR]\n{stderr.decode()}")
        # exit()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=process.returncode,
                cmd=command,
                output=f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
            )
        stdout_decoded = stdout.decode()
        stderr_decoded = stderr.decode()
        # 查找输出的 MinIO 路径
        piste_results_path = None
        for line in stdout_decoded.splitlines():
            if line.startswith("MinIO path: "):
                piste_results_path = line.replace("MinIO path: ", "").strip()
                break
        if piste_results_path is None:
            raise ValueError("MinIO path not found in the output.")
        markdown_content = parse_piste_result(str(piste_results_path))
        
        result = {
            "type": "link",
            "url": piste_results_path or "无有效输出路径",
            "content": markdown_content,
        }
        if piste_results_path:
            logger.info(f"PISTE results saved at {piste_results_path}")
            
        return json.dumps(result, ensure_ascii=False)

    except asyncio.CancelledError:
        logger.error("Task was cancelled")
        raise
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise


@tool
def PISTE(input_file_dir: str, model_name: str = None, threshold: float = None, antigen_type: str = None):
    """
    Run the PISTE tool on a given input file and return results.

    Args:
        input_file_dir (str): MinIO路径，例如 minio://bucket/file.csv
        model_name (str, optional): 使用的模型名，如 random、unipep、reftcr。
        threshold (float, optional): binder判定阈值（0-1）。
        antigen_type (str, optional): 抗原类型，MT 或 WT。

    Returns:
        str: JSON格式的预测结果
    """
    try:
        return asyncio.run(run_PISTE(input_file_dir, model_name, threshold, antigen_type))
    except Exception as e:
        result = {
            "type": "text",
            "content": f"调用PISTE工具失败: {e}"
        }
        return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    input_file = "minio://molly/39e012fc-a8ed-4ee4-8a3b-092664d72862_piste_example.csv"
    print(asyncio.run(run_PISTE(
        input_file,
        model_name="unipep",
        threshold=0.5,
        antigen_type="MT"
    )))
