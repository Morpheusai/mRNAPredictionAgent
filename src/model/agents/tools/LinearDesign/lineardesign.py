import asyncio
import json
import os
import subprocess
import sys
import uuid

from pathlib import Path
from langchain_core.tools import tool
from minio import Minio
from urllib.parse import urlparse

# 当前脚本路径
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parents[4]
sys.path.append(str(project_root))
from config import CONFIG_YAML
from src.utils.log import logger

# 读取 config 中的配置
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_BUCKET = MINIO_CONFIG["lineardesign_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# MinIO 客户端初始化
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

# 配置路径
linear_design_script = CONFIG_YAML["TOOL"]["LINEARDESIGN"]["script"]
input_dir = CONFIG_YAML["TOOL"]["LINEARDESIGN"]["input_tmp_dir"]
output_dir = CONFIG_YAML["TOOL"]["LINEARDESIGN"]["output_tmp_dir"]
linear_design_dir = Path(linear_design_script).parents[0]

if not minio_client.bucket_exists(MINIO_BUCKET):
    minio_client.make_bucket(MINIO_BUCKET)

def download_file_from_minio(minio_path: str, local_dir: str) -> str:
    """下载 MinIO 文件到本地"""
    url_parts = urlparse(minio_path)
    bucket_name = url_parts.netloc
    object_name = url_parts.path.lstrip("/")
    local_dir_path = Path(local_dir)
    local_dir_path.mkdir(parents=True, exist_ok=True)
    local_file_path = local_dir_path / Path(object_name).name

    if not local_file_path.exists():
        logger.info(f"Downloading {minio_path} to {local_file_path}")
        minio_client.fget_object(bucket_name, object_name, str(local_file_path))
    return str(local_file_path)

def upload_file_to_minio(local_file_path: str, remote_name: str = None) -> str:
    """上传本地文件到 MinIO 并返回路径"""
    object_name = remote_name or Path(local_file_path).name
    minio_client.fput_object(MINIO_BUCKET, object_name, local_file_path)
    return f"minio://{MINIO_BUCKET}/{object_name}"

async def run_lineardesign(minio_input_fasta: str, lambda_val: float = 1.0) -> str:
    try:
        
        output_uuid = str(uuid.uuid4())[:8]
        output_filename = f"{output_uuid}_lineardesign_result.fasta"
        local_output = Path(output_dir) / output_filename
        local_output.parent.mkdir(parents=True, exist_ok=True)
        local_input = download_file_from_minio(minio_input_fasta, input_dir)

        # 构建命令
        command = [
            "python", str(linear_design_script),
            "-o", str(local_output),
            "-l", str(lambda_val),
            "-f", str(local_input)
        ]
        #查看命令
        # print(f"Running command: {' '.join(command)}")
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=linear_design_dir  
        )

        # 等待执行结束，收集输出
        stdout, stderr = await process.communicate()
        # print(f"STDOUT: {stdout.decode()}")
        # print(f"STDERR: {stderr.decode()}")
        # exit()
        # 错误处理
        if process.returncode != 0:
            error_message = (
                f"LinearDesign exited with code {process.returncode}\n"
                f"--- stdout ---\n{stdout.decode()}\n"
                f"--- stderr ---\n{stderr.decode()}"
            )
            raise RuntimeError(error_message)

        # 上传结果到 MinIO
        minio_output_path = upload_file_to_minio(str(local_output))
        
        if minio_input_fasta:
            os.remove(local_input)
        os.remove(local_output)
        
        return json.dumps({
            "type": "link",
            "url": minio_output_path,
            "content": f"LinearDesign 运行完成，请下载结果查看"
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({
            "type": "text",
            "content": f"LinearDesign 调用失败：{e}"
        }, ensure_ascii=False)

@tool
def LinearDesign(minio_input_fasta: str , lambda_val: float = 0.5) -> str:
    """
    使用 LinearDesign 工具对给定的肽段或 FASTA 文件进行 mRNA 序列优化。

    参数：
        minio_input_fasta: MinIO 中的输入文件路径（例如 minio://bucket/input.fasta）
        lambda_val: lambda 参数控制表达/结构平衡，默认 0.5

    返回：
        包含 MinIO 链接的 JSON 字符串
    """
    return asyncio.run(run_lineardesign(minio_input_fasta, lambda_val))

if __name__ == "__main__":
    print(asyncio.run(
        run_lineardesign(
            minio_input_fasta="minio://extract-peptide-results/488eaf064dc74baea195075551388008_peptide_sequence.fasta",
            lambda_val= 0.5)))
