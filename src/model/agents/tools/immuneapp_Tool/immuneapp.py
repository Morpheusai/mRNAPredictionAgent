import asyncio
import json
import os
import re
import requests
import subprocess
import sys

from langchain_core.tools import tool
from minio import Minio
from minio.error import S3Error
from pathlib import Path
from urllib.parse import urlparse

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from src.model.agents.tools.immuneapp_Tool.parse_immuneapp_results import parse_immuneapp_results, parse_immuneapp_annotation_results
from src.utils.log import logger
from config import CONFIG_YAML

# ImmuneApp 配置
immuneapp_script = CONFIG_YAML["TOOL"]["IMMUNEAPP"]["script_path"]
immuneapp_python = CONFIG_YAML["TOOL"]["IMMUNEAPP"]["python_bin"]
input_tmp_dir = CONFIG_YAML["TOOL"]["IMMUNEAPP"]["input_tmp_dir"]
output_tmp_dir = CONFIG_YAML["TOOL"]["IMMUNEAPP"]["output_tmp_dir"]
os.makedirs(input_tmp_dir, exist_ok=True)
os.makedirs(output_tmp_dir, exist_ok=True)

# MinIO 配置
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_SECURE = MINIO_CONFIG.get("secure", False)
MINIO_BUCKET = CONFIG_YAML["MINIO"]["immuneapp_bucket"]
DOWNLOAD_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["output_download_url_prefix"]

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)


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
            raise ValueError(
                "Invalid MinIO path format. It should start with 'minio://'.")

        # 解析MinIO路径
        url_parts = urlparse(minio_path)
        bucket_name = url_parts.netloc
        object_name = url_parts.path.lstrip('/')

        if not bucket_name or not object_name:
            raise ValueError(
                "Invalid MinIO path format. It should be 'minio://bucket/object'.")

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
        minio_client.fget_object(
            bucket_name, object_name, str(local_file_path))
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


async def run_ImmuneApp(minio_input_path: str,
                        alleles: str,
                        use_binding_score: bool = True,
                        peptide_lengths: list[int] = None):
    """
    根据输入路径自动判断文件类型（支持 peplist 或 fasta），
    构建并执行 ImmuneApp 命令以进行免疫原性分析。

    参数：
        minio_input_path (str): 输入文件在 MinIO 上的路径。
        alleles (str): HLA 等位基因信息，例如 "HLA-A*02:01,HLA-B*07:02"。
        use_binding_score (bool, 可选): 是否启用结合评分计算。默认启用。
        peptide_lengths (list[int], 可选): 要分析的肽段长度列表，例如 [8, 9, 10]。
    """
    if not minio_input_path.startswith("minio://"):
        raise ValueError(
            f"无效的 MinIO 路径: {minio_input_path}，请确保路径以 'minio://' 开头")
    if check_minio_connection():
        local_input_path = download_file_from_minio(
            minio_input_path, input_tmp_dir)
        suffix = Path(local_input_path).suffix.lower()
    else:
        raise ConnectionError("MinIO连接失败，请检查配置或网络连接。")

    # 自动判断 input_type
    if suffix in [".fa", ".fasta", ".fas"]:
        input_type = "fasta"
    elif suffix in [".txt", ".tsv"]:
        input_type = "peplist"
    else:
        raise ValueError(
            f"不支持的文件类型: {suffix}，请上传 .txt（peplist）或 .fa/.fas/.fasta（fasta）")

    # 设置默认肽段长度（仅 fasta 时有效）
    if input_type == "fasta":
        if peptide_lengths is None:
            peptide_lengths = [9, 10]
            logger.warning("⚠️ 使用FASTA输入未提供 -l 参数，默认使用 [9, 10]。如需修改，请手动指定。")
    output_subdir = Path(output_tmp_dir)
    output_subdir.mkdir(parents=True, exist_ok=True)

    # 构建命令
    command = [immuneapp_python, immuneapp_script]

    if input_type == "fasta":
        command += ["-fa", local_input_path]
        command += ["-l"] + list(map(str, peptide_lengths))
    else:
        command += ["-f", local_input_path]

    command += ["-a"] + [a.strip() for a in alleles.split(',')]

    if use_binding_score:
        command.append("-b")

    command += ["-o", str(output_subdir)]

    try:
        process = await asyncio.create_subprocess_exec(
            *map(str, command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(immuneapp_script)
        )

        stdout, stderr = await process.communicate()
        stdout_text = stdout.decode()
        stderr_text = stderr.decode()
        # print(f"stdout:{stdout_text}")
        # print(f"stderr:{stderr_text}")
        # exit()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=process.returncode,
                cmd=command,
                output=f"stdout: {stdout.decode()}\nstderr: {stderr.decode()}"
            )

        # 正则提取 MinIO 路径
        result_match = re.search(
            r"MinIO ImmuneApp results path:\s+(minio://[^\s]+)", stdout_text)
        annotation_match = re.search(
            r"MinIO ImmuneApp annotation results path:\s+(minio://[^\s]+)", stdout_text)
        if result_match and annotation_match:
            result_path = result_match.group(1)
            annotation_path = annotation_match.group(1)
            immuneapp_content = parse_immuneapp_results(result_path)
            immuneapp_annotation_content = parse_immuneapp_annotation_results(
                annotation_path)
            return json.dumps({
                "type": "link",
                "result_file_url": result_path,  # 预测结果文件
                "annotation_file_url": annotation_path,  # 注释统计文件
                "content": f"ImmuneApp工具执行完成，结果文件已生成。\n\n[预测结果]\n{immuneapp_content}\n\n[注释统计结果]\n{immuneapp_annotation_content}。",
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "type": "text",
                "content": "ImmuneApp工具执行完成，但未找到结果路径"
            }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"ImmuneApp工具执行失败: {e}")
        return json.dumps({
            "type": "text",
            "content": f"ImmuneApp工具执行失败: {e}"
        }, ensure_ascii=False)
# TODO： 加过滤函数：在这里回读minio路径然后下载文件到输出目录中然后读取内容呈现markdown


@tool
def ImmuneApp(input_file_dir: str,
              alleles: str = "HLA-A*01:01,HLA-A*02:01,HLA-A*03:01,HLA-B*07:02",
              use_binding_score: bool = True,
              peptide_lengths: list[int] = None):
    """
    使用 ImmuneApp 工具预测抗原肽段与 MHC 的结合能力。

    自动识别输入类型：
      - .txt → peplist，不需要 -l
      - .fa/.fas/.fasta → fasta，需要 -l（默认 [9,10]）

    参数：
        input_file_dir (str): MinIO 文件路径，如 minio://bucket/file.fas
        alleles (str): 逗号分隔的等位基因列表
        use_binding_score (bool): 是否启用 -b
        peptide_lengths (list[int]): 仅对 fasta 输入有效
    """
    try:
        return asyncio.run(run_ImmuneApp(
            minio_input_path=input_file_dir,
            alleles=alleles,
            use_binding_score=use_binding_score,
            peptide_lengths=peptide_lengths
        ))
    except Exception as e:
        return json.dumps({
            "type": "text",
            "content": f"ImmuneApp工具执行失败: {e}"
        }, ensure_ascii=False)


if __name__ == "__main__":
    print(asyncio.run(run_ImmuneApp(
        minio_input_path="minio://molly/1465d3f7-574b-4c2e-b6e3-0d4c5751333c_immune_test.fasta",
        alleles="HLA-A*01:01,HLA-A*02:01,HLA-A*03:01,HLA-B*07:02",
    )))
