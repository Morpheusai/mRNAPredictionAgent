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
from pathlib import Path

current_file = Path(__file__).resolve()
current_script_dir = current_file.parent
project_root = current_file.parents[5]  # 向上回溯 4 层目录：src/model/agents/tools → src/model/agents → src/model → src → 项目根目录 
sys.path.append(str(project_root))
from config import CONFIG_YAML
from src.utils.log import logger
#动态获取文件路径
pMTnet_script = current_script_dir / "pMTnet_script.py"

pMTnet_env_python = CONFIG_YAML["TOOL"]["PMTNET"]["pMTnet_env_python_dir"]
# pMTnet_script = CONFIG_YAML["TOOL"]["PMTNET"]["pMTnet_script_dir"]

library_dir = CONFIG_YAML["TOOL"]["PMTNET"]["library_dir"]
input_dir = CONFIG_YAML["TOOL"]["PMTNET"]["input_tmp_pmtnet_dir"]
output_dir = CONFIG_YAML["TOOL"]["PMTNET"]["output_tmp_pmtnet_dir"]

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_BUCKET = MINIO_CONFIG["pmtnet_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)


# 定义 pMTnet 虚拟环境的路径    
# pMTnet_env_python = "/mnt/softwares/miniconda3/envs/pmtnet/bin/python"

# 定义 pMTnet 工具的路径
# pMTnet_script = "/mnt/softwares/pMTnet/pMTnet.py"  # 当前脚本路径
# file_dir="/mnt/softwares/pMTnet/tmp/input/test_input.csv" #input protein seq file      #需要调整
# library_dir="/mnt/softwares/pMTnet/library"
# output_dir="/mnt/softwares/pMTnet/tmp/output"

def download_file_from_minio(minio_path: str, local_dir: str, local_file_name: str = None):
    """
    从MinIO下载文件到本地目录。

    :param minio_path: MinIO文件路径，格式为minio://bucket/object
    :param local_dir: 本地目录路径，用于保存下载的文件
    :param local_file_name: 可选，指定下载后的文件名
    """
    try:
        # 验证MinIO路径格式
        if not minio_path.startswith('minio://'):
            raise ValueError("Invalid MinIO path format. It should start with 'minio://'.")
        
        # 解析MinIO路径
        url_parts = urlparse(minio_path)
        bucket_name = url_parts.netloc
        object_name = url_parts.path.lstrip('/')
        
        if not bucket_name or not object_name:
            raise ValueError("Invalid MinIO path format. It should be 'minio://bucket/object'.")
    
        # 确保本地目录存在
        local_dir_path = Path(local_dir)
        local_dir_path.mkdir(parents=True, exist_ok=True)
        
        # 构造本地文件路径
        if local_file_name:
            local_file_path = local_dir_path / local_file_name
        else:
            local_file_path = local_dir_path / Path(object_name).name
        
        # 检查本地文件是否已存在
        if local_file_path.exists():
            logger.info(f"File {local_file_path} already exists.")
            return str(local_file_path)
        
        # 下载文件
        logger.info(f"Downloading {minio_path} to {local_file_path}...")
        minio_client.fget_object(bucket_name, object_name, str(local_file_path))
        logger.info(f"Downloaded {minio_path} to {local_file_path}")
        return str(local_file_path)
    except ValueError as ve:
        # 捕获并处理 ValueError 异常
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

async def run_pMTnet(input_file_dir_minio: str):
    
    if check_minio_connection():
        input_file_dir = download_file_from_minio(input_file_dir_minio, input_dir)

    command = [
        pMTnet_env_python,
        pMTnet_script,
        "-input", input_file_dir,
        "-library", library_dir,
        "-output", output_dir
    ]

    try:
        # 使用 subprocess 运行命令
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 等待进程完成并获取输出
        stdout, stderr = await process.communicate()

        # 检查进程是否成功完成
        if process.returncode != 0:
            error_message = f"Subprocess exited with return code {process.returncode}\n"
            error_message += f"stdout: {stdout.decode()}\n"
            error_message += f"stderr: {stderr.decode()}"
            raise subprocess.CalledProcessError(returncode=process.returncode, cmd=command, output=error_message)
        # 解码 stdout 和 stderr
        stdout_decoded = stdout.decode()
        stderr_decoded = stderr.decode()

        # 提取 MinIO 路径
        pmtnet_results_path = None
        for line in stdout_decoded.split('\n'):
            if line.startswith('MinIO path: '):
                pmtnet_results_path = line[len('MinIO path: '):].strip()
                break

        # 返回结果
        text_content="已成功完成pMHC-TCR结合预测"
        result = {
        "type": "link",
        "url": pmtnet_results_path,
        "content": text_content,
        }     
        return json.dumps(result, ensure_ascii=False)  

    except asyncio.CancelledError:
        # 处理任务被取消的情况
        print("Task was cancelled")
        raise

    except Exception as e:
        # 捕获其他异常
        print(f"An error occurred: {e}")
        raise
@tool
def pMTnet(input_file_dir: str ):
    """
     Run the pMTnet tool on a given input file directory and return the results.
     Args:
         input_file_dir (str): The path to the input file directory.
     Returns:
         str: The JSON-formatted results of the pMTnet analysis.
    """
    try:
        return asyncio.run(run_pMTnet(input_file_dir))
    except Exception as e:
        result = {
                "type": "text",
                "content": f"调用ExtractPeptide工具失败: {e}"
            }
        return json.dumps(result, ensure_ascii=False)

# 如果直接运行 pMTnet.py，则执行 run_pMTnet 函数
if __name__ == "__main__":
    print(asyncio.run(run_pMTnet("minio://molly/66dd7c86-f1c4-455e-9e50-3b2a77be66c9_test_input.csv")))