import asyncio
import json
import os
import sys
import uuid

from dotenv import load_dotenv
from langchain_core.tools import tool
from minio import Minio
from minio.error import S3Error
from pathlib import Path

from src.model.agents.tools.netmhcstabpan_Tool.filter_netmhcstabpan import filter_netmhcstabpan_output
from src.model.agents.tools.netmhcstabpan_Tool.netmhcstabpan_to_excel import save_excel
load_dotenv()
current_file = Path(__file__).resolve()
project_root = current_file.parents[4]  # 向上回溯 4 层目录：src/model/agents/tools → src/model/agents → src/model → src → 项目根目录
                                        
# 将项目根目录添加到 sys.path
sys.path.append(str(project_root))
from config import CONFIG_YAML

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_BUCKET = MINIO_CONFIG["netmhcstabpan_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# netMHCstabpan 配置 #TODO: 添加netmhcstabpan_dir 配置文件
NETMHCSTABPAN_DIR = CONFIG_YAML["TOOL"]["NETMHCSTABPAN"]["netmhcstabpan_dir"]
INPUT_TMP_DIR = CONFIG_YAML["TOOL"]["NETMHCSTABPAN"]["input_tmp_netmhcstabpan_dir"]
DOWNLOADER_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["output_download_url_prefix"]
OUTPUT_TMP_DIR = CONFIG_YAML["TOOL"]["NETMHCSTABPAN"]["output_tmp_netmhcstabpan_dir"]

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)
#检查minio是否可用
def check_minio_connection(bucket_name=MINIO_BUCKET):
    try:
        minio_client.list_buckets()
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        return True
    except S3Error as e:
        print(f"MinIO连接或bucket操作失败: {e}")
        return False


async def run_netmhcstabpan(
    input_file: str,  # MinIO 文件路径，格式为 "bucket-name/file-path"
    mhc_allele: str = "HLA-A02:01",  # MHC 等位基因类型
    high_threshold_of_bp: float = 0.5,  # 相对阈值上限
    low_threshold_of_bp: float = 2.0,  # 相对阈值下限
    peptide_length: str = "8,9,10,11",  # 肽段长度，逗号分隔
    netmhcstabpan_dir: str = NETMHCSTABPAN_DIR
    ) -> str:

    """
    异步运行 netMHCstabpan 并将处理后的结果上传到 MinIO
    :param input_file: MinIO 文件路径，格式为 "bucket-name/file-path"
    :param mhc_allele: MHC 等位基因类型
    :param high_threshold_of_bp: 相对阈值上限
    :param low_threshold_of_bp: 相对阈值下限
    :param peptide_length: 肽段长度，逗号分隔（如 "8,9"）
    :param netmhcstabpan_dir: netMHCstabpan 安装目录
    :return: JSON 字符串，包含 MinIO 文件路径（或下载链接）
    """

    minio_available = check_minio_connection()
    #提取桶名和文件
    try:
        # 去掉 minio:// 前缀
        path_without_prefix = input_file[len("minio://"):]
        
        # 找到第一个斜杠的位置，用于分割 bucket_name 和 object_name
        first_slash_index = path_without_prefix.find("/")
        
        if first_slash_index == -1:
            raise ValueError("Invalid file path format: missing bucket name or object name")
        
        # 提取 bucket_name 和 object_name
        bucket_name = path_without_prefix[:first_slash_index]
        object_name = path_without_prefix[first_slash_index + 1:]
        
        # 打印提取结果（可选）
        # logger.info(f"Extracted bucket_name: {bucket_name}, object_name: {object_name}")
        
    except Exception as e:
        # logger.error(f"Failed to parse file_path: {file_path}, error: {str(e)}")
        raise str(status_code=400, detail=f"Failed to parse file path: {str(e)}")     

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
    input_dir = Path(INPUT_TMP_DIR)
    output_dir =Path(OUTPUT_TMP_DIR)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 写入输入文件
    input_path = input_dir / f"{random_id}.fsa"
    with open(input_path, "w") as f:
        f.write(file_content)

    # 构建输出文件名和临时路径
    output_filename = f"{random_id}_NetMHCstabpan_results.xlsx"
    output_path = output_dir / output_filename

    # 构建命令
    cmd = [
        f"{netmhcstabpan_dir}/bin/netMHCstabpan",
        "-rht", str(high_threshold_of_bp),
        "-rlt", str(low_threshold_of_bp),
        "-l", peptide_length,
        "-a", mhc_allele,
        str(input_path)
    ]
    # 启动异步进程
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=f"{netmhcstabpan_dir}/bin"
        )
    except FileNotFoundError as e:
        result = {
            "type": "text",
            "content": f"工具未找到，请检查路径: {netmhcstabpan_dir}/bin/netMHCstabpan。错误: {str(e)}"
        }
        return json.dumps(result, ensure_ascii=False)
    
    # 获取输出
    stdout, stderr = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace")

    save_excel(output,output_dir,output_filename)

    # with open(output_path, "w") as f:
    #     f.write("\n".join(output.splitlines()))

    filtered_content = filter_netmhcstabpan_output(output.splitlines())
    if proc.returncode != 0:
        error_msg = stderr.decode()
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        result ={
            "type": "text",
            "content": f"您的输入信息可能有误，请核对正确再试。"
        }
        return json.dumps(result, ensure_ascii=False)
    # 写入文件
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
        "content": filtered_content  # 替换为生成的Markdown内容
    }

    return json.dumps(result, ensure_ascii=False)

@tool
def NetMHCstabpan(input_file: str,
                  mhc_allele: str = "HLA-A02:01",
                  high_threshold_of_bp: float = 0.5,
                  low_threshold_of_bp: float = 2.0,
                  peptide_length: str = "8,9,10,11",) -> str:
    """                                    
    NetMHCstabpan用于预测肽段与MHC结合后复合物的稳定性，可用于优化疫苗设计和免疫治疗。
    Args:
        input_file (str): 输入的肽段序列fasta文件路径 
        mhc_allele (str): MHC比对的等位基因
        peptide_length (str): 预测时所使用的肽段长度            
        high_threshold_of_bp (float): 肽段和MHC分子高结合能力的阈值
        low_threshold_of_bp (float): 肽段和MHC分子弱结合能力的阈值
    Returns:
        str: 返回高稳定性的肽段序列信息                                                                                                                           
    """
    try:
        return asyncio.run(run_netmhcstabpan(input_file,
                                             mhc_allele,
                                             high_threshold_of_bp,
                                             low_threshold_of_bp,
                                             peptide_length))
    except RuntimeError as e:
        return f"调用NetMHCstabpan工具失败: {e}"
    except Exception as e:
        return f"调用NetMHCstabpan工具失败: {e}"
    
