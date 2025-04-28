import asyncio
import json
import os
import subprocess
import sys
import uuid

from langchain_core.tools import tool
from minio import Minio
from minio.error import S3Error
from pathlib import Path
from urllib.parse import urlparse

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from src.utils.log import logger
from config import CONFIG_YAML
from src.model.agents.tools.TransPHLA.parse_transphla_results import parse_transphla_results

# TransPHLA 配置
transphla_script = CONFIG_YAML["TOOL"]["TRANSPHLA"]["script_path"]
transphla_python = CONFIG_YAML["TOOL"]["TRANSPHLA"]["python_bin"]
input_tmp_dir = CONFIG_YAML["TOOL"]["TRANSPHLA"]["input_tmp_dir"]
output_tmp_dir = CONFIG_YAML["TOOL"]["TRANSPHLA"]["output_tmp_dir"]
os.makedirs(input_tmp_dir, exist_ok=True)
os.makedirs(output_tmp_dir, exist_ok=True)

# MinIO配置
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_SECURE = MINIO_CONFIG.get("secure", False)
MINIO_BUCKET = MINIO_CONFIG["transphla_bucket"]

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

def download_file_from_minio(minio_path: str, local_dir: str):
    url_parts = urlparse(minio_path)
    bucket_name = url_parts.netloc
    object_name = url_parts.path.lstrip('/')
    local_dir_path = Path(local_dir)
    local_dir_path.mkdir(parents=True, exist_ok=True)
    local_file_path = local_dir_path / Path(object_name).name
    if not local_file_path.exists():
        minio_client.fget_object(bucket_name, object_name, str(local_file_path))
    return str(local_file_path)


async def run_TransPHLA(peptide_minio_path: str,
                        hla_minio_path: str,
                        threshold: float = 0.5,
                        cut_length: int = 10,
                        cut_peptide: bool = True):
    try:
        # 下载输入文件
        peptide_local_path = download_file_from_minio(peptide_minio_path, input_tmp_dir)
        hla_local_path = download_file_from_minio(hla_minio_path, input_tmp_dir)

        # 输出目录设置
        result_uuid = str(uuid.uuid4())
        output_dir = Path(output_tmp_dir) / f"{result_uuid}_transphla"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 构造执行命令
        command = [
            transphla_python, transphla_script,
            "--peptide_file", peptide_local_path,
            "--HLA_file", hla_local_path,
            "--threshold", str(threshold),
            "--cut_length", str(cut_length),
            "--cut_peptide", str(cut_peptide),
            "--output_dir", str(output_dir),
            "--output_attention", "True",
            "--output_heatmap", "True",
            "--output_mutation", "True"
        ]

        process = await asyncio.create_subprocess_exec(
            *map(str, command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(transphla_script),
        )

        stdout, stderr = await process.communicate()
        # print(f"TransPHLA输出: {stdout.decode()}"
        #       f"TransPHLA错误: {stderr.decode()}")
        # exit()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command, output=stderr.decode())
        
        logger.info(f"TransPHLA运行成功，结果在: {output_dir}")

        # 上传结果目录下所有文件回 MinIO
        
        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)
            logger.info(f"创建 MinIO 存储桶: {MINIO_BUCKET}")
        
        for file in output_dir.glob("*"):
            if file.is_dir():
                logger.info(f"Skipping directory: {file}")
                continue

            if not file.exists():
                logger.warning(f"File not found: {file}")
                continue
            try:
                logger.info(f"Uploading {file} to MinIO...")
                object_path = f"{result_uuid}_transphla_{file.name}"
                minio_client.fput_object(
                    bucket_name=MINIO_BUCKET,
                    object_name=object_path,
                    file_path=str(file)
                )
        
            except Exception as e:
                logger.error(f"Failed to upload {file}: {e}")
        file_path = f"minio://{MINIO_BUCKET}/{object_path}"
        parse_content = parse_transphla_results(file_path)
        
        #清理输入文件和输出目录
        try:
            if os.path.exists(peptide_local_path):
                os.remove(peptide_local_path)
                logger.info(f"删除输入文件: {peptide_local_path}")
            if os.path.exists(hla_local_path):
                os.remove(hla_local_path)
                logger.info(f"删除输入文件: {hla_local_path}")
            if output_dir.exists():
                for item in output_dir.glob("*"):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        for sub in item.rglob("*"):
                            if sub.is_file():
                                sub.unlink()
                        item.rmdir()
                output_dir.rmdir()
                logger.info(f"删除输出目录: {output_dir}")
        except Exception as cleanup_err:
            logger.warning(f"清理临时文件失败: {cleanup_err}")
        
        return json.dumps({
            "type": "link",
            "url": file_path,
            "content": parse_content
        }, ensure_ascii=False)
    
    except Exception as e:
        logger.error(f"TransPHLA运行失败: {e}")
        return json.dumps({
            "type": "text",
            "content": f"TransPHLA运行失败: {e}"
        }, ensure_ascii=False)
@tool
def TransPHLA_AOMP(peptide_file: str,
                   hla_file: str,
                   threshold: float = 0.5,
                   cut_length: int = 10,
                   cut_peptide: bool = True):
    """
    使用 TransPHLA_AOMP 工具预测肽段与 HLA 的结合能力，并自动返回结果文件链接。

    参数说明：
    - peptide_file: MinIO 中的肽段 FASTA 文件路径（如 minio://bucket/peptides.fasta）
    - hla_file: MinIO 中的 HLA FASTA 文件路径（如 minio://bucket/hlas.fasta）
    - threshold: 绑定预测阈值，默认使用 0.5
    - cut_length: 肽段最大切割长度
    - cut_peptide: 是否启用肽段切割处理（True/False）

    返回值：
    - JSON 字符串，包含url和 markdown 格式的输出说明
    """
    try:
        return asyncio.run(run_TransPHLA(
            peptide_minio_path=peptide_file,
            hla_minio_path=hla_file,
            threshold=threshold,
            cut_length=cut_length,
            cut_peptide=cut_peptide
        ))
    except Exception as e:
        return json.dumps({
            "type": "text",
            "content": f"❌ TransPHLA工具运行失败: {e}"
        }, ensure_ascii=False)
        
        
if __name__ == "__main__":
    print(asyncio.run(run_TransPHLA(
        peptide_minio_path="minio://molly/c2a3fc7e-acdb-483c-8ce4-3532ebb96136_peptides.fasta",
        hla_minio_path="minio://molly/29959599-2e39-4a66-a22d-ccfb86dedd21_hlas.fasta"
    )))