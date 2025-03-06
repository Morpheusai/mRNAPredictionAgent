import asyncio
import sys
import json
from langchain_core.tools import tool
from pathlib import Path
import uuid
from minio import Minio
from minio.error import S3Error

current_file = Path(__file__).resolve()
project_root = current_file.parents[4]  # 向上回溯 4 层目录：src/model/agents/tools → src/model/agents → src/model → src → 项目根目录
                                        
# 将项目根目录添加到 sys.path
sys.path.append(str(project_root))
from config import CONFIG_YAML

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = MINIO_CONFIG["access_key"]
MINIO_SECRET_KEY = MINIO_CONFIG["secret_key"]
MINIO_BUCKET = MINIO_CONFIG["netmhcpan_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# netMHCpan 配置 
NETMHCPAN_DIR = CONFIG_YAML["TOOL"]["netmhcpan_dir"]
INPUT_TMP_DIR = CONFIG_YAML["TOOL"]["input_tmp_upload_dir"]
DOWNLOADER_PREFIX = CONFIG_YAML["TOOL"]["output_download_url_prefix"]
OUTPUT_TMP_DIR = CONFIG_YAML["TOOL"]["output_tmp_netmhcpan_dir"]

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


def filter_netmhcpan_output(output_lines: list) -> str:
    """
    过滤 netMHCpan 的输出，提取关键信息并生成 Markdown 表格
    
    Args:
        output_lines (list): netMHCpan 的原始输出内容（按行分割的列表）
        
    Returns:
        str: 生成的 Markdown 表格字符串
    """
    import re

    # 初始化变量
    filtered_data = []

    # 遍历每一行输出
    for line in output_lines:
        line = line.strip()
        

        # 确保是有效数据行（列数 >= 14）并且行包含"WB"或"SB"
        if ("WB" in line or "SB" in line):
            # 处理数据行（关键修改部分）
            parts = line.split()
            try:
                # 提取 HLA, Peptide, BindLevel 和 Affinity
                hla = parts[1]  # HLA 在第二个位置
                peptide = parts[2]   # 处理长肽段
                bind_level = "WB" if "WB" in line else "SB" if "SB" in line else "N/A"  # 判断 BindLevel 是 WB 还是 SB
                affinity = parts[-3]  # 亲和力是最后一个值
                
                # 将数据添加到 filtered_data
                filtered_data.append({
                    "Peptide": peptide,
                    "HLA": hla,
                    "BindLevel": bind_level,
                    "Affinity": affinity
                })
            except IndexError:
                continue
    # 生成Markdown表格
    markdown_content = [
        "| Peptide Sequence | HLA Allele | Bind Level | Affinity (nM) |",
        "|------------------|------------|------------|---------------|"
    ]
    
    for item in filtered_data:
        markdown_content.append(
            f"| {item['Peptide']} | {item['HLA']} | {item['BindLevel']} | {item['Affinity']} |"
        )
    
    # 添加统计信息
    markdown_content.append(
            f'| <td colspan="4">{output_lines[-3]}</td> |' 
        )
    return "\n".join(markdown_content)

async def run_netmhcpan(
    minio_file_path: str,  # MinIO 文件路径，格式为 "bucket-name/file-path"
    allele: str = "HLA-A02:01",  # MHC 等位基因类型
    rth: float = 0.5,  # 相对阈值上限
    rlt: float = 2.0,  # 相对阈值下限
    lengths: str = "8,9,10,11",  # 肽段长度，逗号分隔
    netmhcpan_dir: str = NETMHCPAN_DIR
    ) -> str:
    """
    异步运行 netMHCpan 并将处理后的结果上传到 MinIO
    :param minio_file_path: MinIO 文件路径，格式为 "bucket-name/file-path"
    :param allele: MHC 等位基因类型
    :param rth: 相对阈值上限
    :param rlt: 相对阈值下限
    :param lengths: 肽段长度，逗号分隔（如 "8,9"）
    :param netmhcpan_dir: netMHCpan 安装目录
    :return: JSON 字符串，包含 MinIO 文件路径（或下载链接）
    """

    minio_available = check_minio_connection()
    #提取桶名和文件
    try:
        # 去掉 minio:// 前缀
        path_without_prefix = minio_file_path[len("minio://"):]
        
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
            "type": "error",
            "content": f"无法从 MinIO 读取文件: {str(e)}"
        }, ensure_ascii=False)    

    # 生成随机ID和文件路径
    random_id = uuid.uuid4().hex
    #base_path = Path(__file__).resolve().parents[3]  # 根据文件位置调整层级
    input_dir = Path(INPUT_TMP_DIR)
    output_dir =Path(OUTPUT_TMP_DIR)
    
    # 创建目录
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 写入输入文件
    input_path = input_dir / f"{random_id}.fsa"
    with open(input_path, "w") as f:
        f.write(file_content)

    # 构建输出文件名和临时路径
    output_filename = f"netmhcpan_result_{random_id}.txt"
    output_path = output_dir / output_filename

    # 构建命令
    cmd = [
        f"{netmhcpan_dir}/bin/netMHCpan",
        "-BA",
        "-rth", str(rth),  # 添加 -rth 参数
        "-rlt", str(rlt),  # 添加 -rlt 参数
        "-l", lengths,      # 添加 -l 参数
        "-a", allele,       # 添加 -a 参数
        str(input_path)     # 输入文件路径
    ]

    # 启动异步进程
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=f"{netmhcpan_dir}/bin"
    )

    # 处理输出
    stdout, stderr = await proc.communicate()
    output = stdout.decode()
    # 直接将所有内容写入文件
    with open(output_path, "w") as f:
        f.write("\n".join(output.splitlines()))
    # 调用过滤函数
    filtered_content = filter_netmhcpan_output(output.splitlines())
    # 错误处理
    if proc.returncode != 0:
        error_msg = stderr.decode()
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        result ={
            "type": "text",
            "content": "您的输入信息可能有误，请核对正确再试。"
        }

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
def NetMHCpan(minio_file_path: str,allele: str = "HLA-A02:01",rth: float = 0.5,rlt: float = 2.0,lengths: str = "8,9,10,11",) -> str:
    """
    Use the NetMHCpan model to predict neoantigens based on the input file content.

    Args:
        minio_file_path (str): Path to the tumor variant protein sequence file. This is a required input with no default value. 
                               The uploaded data content must be validated for legitimacy. If invalid, the user must re-upload the data.
        allele (str, optional): HLA typing data. This is optional, with a default value of "HLA-A02:01".
        rth (float, optional): Strong binding threshold. This is optional, with a default value of 0.5.
        rlt (float, optional): Weak binding threshold. This is optional, with a default value of 2.0.
        lengths (str, optional): Peptide prediction lengths. This is optional, with a default value of "9".

    Returns:
        str: Returns the prediction results in string format. 
    """
    try:
        return asyncio.run(run_netmhcpan(minio_file_path,allele,rth,rlt,lengths))
    except RuntimeError as e:
        return f"调用NetMHCpan工具失败: {e}"
    except Exception as e:
        return f"调用NetMHCpan工具失败: {e}"
    
