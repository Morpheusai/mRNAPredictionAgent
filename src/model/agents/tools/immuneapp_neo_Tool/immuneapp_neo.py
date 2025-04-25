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
from src.model.agents.tools.immuneapp_neo_Tool.parse_immuneapp_neo_results import parse_immuneapp_neo_results
from src.utils.log import logger
from config import CONFIG_YAML

# ImmuneApp 配置
immuneapp_neo_script = CONFIG_YAML["TOOL"]["IMMUNEAPP_NEO"]["script_path"]
immuneapp_python = CONFIG_YAML["TOOL"]["IMMUNEAPP_NEO"]["python_bin"]
input_tmp_dir = CONFIG_YAML["TOOL"]["IMMUNEAPP_NEO"]["input_tmp_dir"]
output_tmp_dir = CONFIG_YAML["TOOL"]["IMMUNEAPP_NEO"]["output_tmp_dir"]
os.makedirs(input_tmp_dir, exist_ok=True)
os.makedirs(output_tmp_dir, exist_ok=True)

# MinIO 配置
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_SECURE = MINIO_CONFIG.get("secure", False)
MINIO_BUCKET = CONFIG_YAML["MINIO"]["immuneapp_neo_bucket"]

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

def download_file_from_minio(minio_path: str, local_dir: str):
    """
    从 MinIO 下载文件到本地目录
    """
    if not minio_path.startswith('minio://'):
        raise ValueError("输入路径必须是 MinIO 格式，如 'minio://bucket/file'")

    url_parts = urlparse(minio_path)
    bucket_name = url_parts.netloc
    object_name = url_parts.path.lstrip('/')

    local_path = Path(local_dir) / Path(object_name).name
    Path(local_dir).mkdir(parents=True, exist_ok=True)

    if not local_path.exists():
        logger.info(f"Downloading {minio_path} to {local_path}")
        minio_client.fget_object(bucket_name, object_name, str(local_path))

    return str(local_path)


async def run_ImmuneApp_Neo(input_file: str, alleles: str):
    """
    执行 ImmuneApp-Neo 命令以预测 neoepitope 的免疫原性，仅支持 peplist 文件输入。

    参数：
        minio_input_path (str): 输入文件在 MinIO 上的路径。
        alleles (str): HLA 等位基因信息，例如 "HLA-A*02:01,HLA-B*07:02"。
    """
    if not input_file.startswith("minio://"):
        raise ValueError(f"无效的 MinIO 路径: {input_file}，请确保路径以 'minio://' 开头")

    local_input_path = download_file_from_minio(input_file, input_tmp_dir)
    suffix = Path(local_input_path).suffix.lower()

    if suffix not in [".txt", ".tsv"]:
        raise ValueError(
            f"不支持的文件类型: {suffix}，请上传 .txt 或 .tsv（peplist）文件")
    
    result_uuid = str(uuid.uuid4())
    output_dir = Path(output_tmp_dir) / f"{result_uuid}_immuneapp_neo"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 构建命令
    command = [immuneapp_python, immuneapp_neo_script, "-f", local_input_path]

    alleles_list = [a.strip() for a in alleles.split(',')]
    command += ["-a"] + alleles_list

    command += ["-o", str(output_dir)]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(immuneapp_neo_script)
        )

        stdout, stderr = await process.communicate()
        stdout_text = stdout.decode()
        stderr_text = stderr.decode()
        # print(f"stdout: {stdout_text}")
        # print(f"stderr: {stderr_text}")
        
        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=process.returncode,
                cmd=command,
                output=f"stdout: {stdout_text}\nstderr: {stderr_text}"
            )
        logger.info(f"ImmuneApp-Neo 执行成功，输出目录: {output_dir}")

        # 上传输出文件到 MinIO
        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)
            logger.info(f"创建 MinIO 存储桶: {MINIO_BUCKET}")
        try:
            for file in output_dir.iterdir():
                if file.is_file():
                    object_name = f"{result_uuid}_{file.name}"
                    minio_client.fput_object(
                        MINIO_BUCKET,
                        object_name,
                        str(file)
                    )
                    logger.info(f"文件 {file.name} 已上传到 MinIO，路径: minio://{MINIO_BUCKET}/{object_name}")
                    file_path = f"minio://{MINIO_BUCKET}/{object_name}"
        except Exception as upload_error:
            logger.error(f"文件上传到 MinIO 失败: {upload_error}")
            return json.dumps({
                "type": "text",
                "content": f"文件上传到 MinIO 失败: {upload_error}"
            }, ensure_ascii=False)
        # 解析结果文件
        immuneapp_content = parse_immuneapp_neo_results(file_path)
        # 删除输入和输出的临时文件
        try:
            # 删除输入文件
            if Path(local_input_path).exists():
                os.remove(local_input_path)
                logger.info(f"已删除输入文件: {local_input_path}")

            # 删除输出目录及其内容
            if output_dir.exists():
                for file in output_dir.iterdir():
                    file.unlink()  # 删除文件
                output_dir.rmdir()  # 删除目录
                logger.info(f"已删除输出目录: {output_dir}")
        except Exception as cleanup_error:
            logger.error(f"清理临时文件失败: {cleanup_error}")
            
        return json.dumps({
            "type": "link",
            "url": file_path,
            "content": immuneapp_content
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"ImmuneApp_Neo执行失败: {e}")
        return json.dumps({
            "type": "text",
            "content": f"ImmuneApp_Neo工具执行失败: {e}"
        }, ensure_ascii=False)


@tool
def ImmuneApp_Neo(input_file: str,
              alleles: str = "HLA-A*01:01,HLA-A*02:01,HLA-A*03:01,HLA-B*07:02"):
    """
    使用 ImmuneApp-Neo 工具预测 neoepitope 的免疫原性，针对 HLA-I 抗原表位。

    该工具从 MinIO 下载输入文件，运行 ImmuneApp-Neo 脚本，并返回预测结果。
    仅支持 peplist 文件格式（.txt 或 .tsv），包含肽序列列表。

    参数：
        input_file (str): MinIO 文件路径，例如 minio://bucket/file.txt。
        alleles (str): 逗号分隔的 HLA-I 等位基因列表，例如 "HLA-A*01:01,HLA-A*02:01"。

    返回：
        JSON 格式的字符串，包含：
        - 如果脚本输出 MinIO 结果路径：包含结果文件 URL 和解析内容的 "link" 类型响应。
        - 否则：包含执行状态或错误信息的 "text" 类型响应。
    """
    try:
        return asyncio.run(run_ImmuneApp_Neo(
            input_file=input_file,
            alleles=alleles
        ))
    except Exception as e:
        return json.dumps({
            "type": "text",
            "content": f"ImmuneApp_Neo执行失败: {e}"
        }, ensure_ascii=False)


# 示例执行
if __name__ == "__main__":
    print(asyncio.run(run_ImmuneApp_Neo(
        input_file="minio://molly/3a39b343-8e2e-4957-8256-55f9bdaae0a6_test_immunogenicity.txt",
        alleles="HLA-A*01:01,HLA-A*02:01,HLA-A*03:01,HLA-B*07:02"
    )))
