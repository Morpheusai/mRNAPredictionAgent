import asyncio
import json
import os
import sys
import uuid

from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error
from langchain_core.tools import tool
from pathlib import Path


load_dotenv()
current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
# 将项目根目录添加到 sys.path
sys.path.append(str(project_root))
from src.model.agents.tools.netctlpan_Tool.filter_netctlpan import filter_netctlpan_output
from src.model.agents.tools.netctlpan_Tool.netctlpan_to_excel import save_excel
from config import CONFIG_YAML

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_BUCKET = MINIO_CONFIG["netctlpan_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# netCTLpan 配置
NETCTLPAN_DIR = CONFIG_YAML["TOOL"]["NETCTLPAN"]["netctlpan_dir"]
INPUT_TMP_DIR = CONFIG_YAML["TOOL"]["NETCTLPAN"]["input_tmp_netctlpan_dir"]
DOWNLOADER_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["output_download_url_prefix"]
OUTPUT_TMP_DIR = CONFIG_YAML["TOOL"]["NETCTLPAN"]["output_tmp_netctlpan_dir"]

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)
# 检查minio是否可用


def check_minio_connection(bucket_name=MINIO_BUCKET):
    try:
        minio_client.list_buckets()
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        return True
    except S3Error as e:
        print(f"MinIO连接或bucket操作失败: {e}")
        return False


async def run_netctlpan(
    input_file: str,  # MinIO 文件路径，格式为 "bucket-name/file-path"
    mhc_allele: str = "HLA-A02:01",  # MHC 等位基因类型
    weight_of_clevage: float = 0.225,  # 相对阈值上限
    weight_of_tap: float = 0.025,  # 相对阈值下限
    peptide_length: str = "8,9,10,11",  # 肽段长度，默认是9
    netctlpan_dir: str = NETCTLPAN_DIR
) -> str:
    """
    异步运行 netCTLpan 并返回结果
    :param input_file: MinIO 文件路径，格式为 "bucket-name/file-path"
    :param mhc_allele: MHC 等位基因类型
    :param weight_of_tap: TAP 的权重
    :param weight_of_clevage: Clevage 的权重
    :param peptide_length: 肽段长度
    :param netctlpan_dir: netCTLpan 安装目录
    :return: 处理结果字符串
    """

    minio_available = check_minio_connection()
    # 提取桶名和文件
    try:
        # 去掉 minio:// 前缀
        path_without_prefix = input_file[len("minio://"):]

        # 找到第一个斜杠的位置，用于分割 bucket_name 和 object_name
        first_slash_index = path_without_prefix.find("/")

        if first_slash_index == -1:
            raise ValueError(
                "Invalid file path format: missing bucket name or object name")

        # 提取 bucket_name 和 object_name
        bucket_name = path_without_prefix[:first_slash_index]
        object_name = path_without_prefix[first_slash_index + 1:]

        # 打印提取结果（可选）
        # logger.info(f"Extracted bucket_name: {bucket_name}, object_name: {object_name}")

    except Exception as e:
        # logger.error(f"Failed to parse file_path: {file_path}, error: {str(e)}")
        raise str(status_code=400,
                  detail=f"Failed to parse file path: {str(e)}")

    try:
        response = minio_client.get_object(bucket_name, object_name)
        file_content = response.read().decode("utf-8")
    except S3Error as e:
        return json.dumps({
            "type": "text",
            "content": f"无法从 MinIO 读取文件: {str(e)}"
        }, ensure_ascii=False)

    # 生成随机ID和文件路径
    random_id = uuid.uuid4().hex
    # base_path = Path(__file__).resolve().parents[3]  # 根据文件位置调整层级
    input_dir = Path(INPUT_TMP_DIR)
    output_dir = Path(OUTPUT_TMP_DIR)

    # 创建目录
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 写入输入文件
    input_path = input_dir / f"{random_id}.fsa"
    with open(input_path, "w") as f:
        f.write(file_content)

    # 构建输出文件名和临时路径
    output_filename = f"{random_id}_NetCTLpan_results.xlsx"
    output_path = output_dir / output_filename

    # 构建命令
    cmd = [
        f"{netctlpan_dir}/netCTLpan",
        "-wt", str(weight_of_tap),
        "-wc", str(weight_of_clevage),
        "-l", peptide_length,
        "-a", mhc_allele,
        str(input_path)
    ]

    # 启动异步进程
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=f"{netctlpan_dir}"
    )

    # 处理输出
    stdout, stderr = await proc.communicate()
    output = stdout.decode()
    # print(output)
    save_excel(output, output_dir, output_filename)

    # 调用过滤函数
    filtered_content = filter_netctlpan_output(output.splitlines())
    # print(f"filtered_content：{filtered_content}")

    # 错误处理
    if proc.returncode != 0:
        error_msg = stderr.decode()
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        result = {
            "type": "text",
            "content": "您的输入信息可能有误，请核对正确再试。"
        }
    else:
        try:
            if minio_available:
                minio_client.fput_object(
                    MINIO_BUCKET,
                    output_filename,
                    str(output_path)
                )
                file_path = f"minio://{MINIO_BUCKET}/{output_filename}"
            else:
                # 如果 MinIO 不可用，返回下载链接
                file_path = f"{DOWNLOADER_PREFIX}{output_filename}"
        except S3Error as e:
            file_path = f"{DOWNLOADER_PREFIX}{output_filename}"
        finally:
            # 如果 MinIO 成功上传，清理临时文件；否则保留
            if minio_available:
                input_path.unlink(missing_ok=True)
                output_path.unlink(missing_ok=True)
            else:
                input_path.unlink(missing_ok=True)  # 只删除输入文件，保留输出文件

        # 返回结果
        result = {
            "type": "link",
            "url": file_path,
            "content": filtered_content  # 替换为生成的 Markdown 内容
        }

    return json.dumps(result, ensure_ascii=False)


@tool
def NetCTLpan(input_file: str, mhc_allele: str = "HLA-A02:01", weight_of_clevage: float = 0.225,
              weight_of_tap: float = 0.025, peptide_length: str = "8,9,10,11") -> str:
    """
    使用NetCTLpan工具预测肽段序列与指定MHC分子的结合亲和力，用于筛选潜在的免疫原性肽段。
    该函数结合蛋白质裂解、TAP转运和MHC结合的预测，适用于疫苗设计和免疫研究。

    :param input_file: 输入的FASTA格式肽段序列文件路径
    :param mhc_allele: 用于比对的MHC等位基因名称，默认为"HLA-A02:01"
    :param weight_of_clevage: 蛋白质裂解预测的权重，默认为0.225
    :param weight_of_tap: TAP转运效率预测的权重，默认为0.025
    :param peptide_length: 预测的肽段长度范围，默认为"9"
    :return: 返回预测结果字符串，包含高亲和力肽段信息
    """
    try:
        # 调用异步函数并获取返回结果
        result = asyncio.run(run_netctlpan(
            input_file, mhc_allele, weight_of_clevage, weight_of_tap, peptide_length))

        # 可以根据需要在这里对结果进行更多处理
        return result

    except Exception as e:
        # 捕获并返回异常信息
        result = {
            "type": "text",
            "content": f"调用NetMHCpan工具失败: {str(e)}"
        }
        return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    print(asyncio.run(run_netctlpan(
        input_file="minio://molly/2ad83c64-0440-4d70-80bf-8a0054c0ecac_B0702.fsa", peptide_length="9")))
