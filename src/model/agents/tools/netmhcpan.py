import asyncio
import sys
import json
from langchain.tools import tool
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
MINIO_BUCKET = MINIO_CONFIG["bucket"]
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

async def run_netmhcpan(
    input_filecontent: str, 
    #    allele: str = "HLA-A02:01",
    netmhcpan_dir: str = NETMHCPAN_DIR
    ) -> str:
    """
    异步运行netMHCpan并将处理后的结果上传到MinIO
    :param input_filecontent: 输入文件内容
    :param allele: MHC等位基因类型
    :param netmhcpan_dir: netMHCpan安装目录
    :return: JSON字符串包含MinIO文件路径（或下载链接）
    """

    minio_available = check_minio_connection()

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
        f.write(input_filecontent)

    # 构建输出文件名和临时路径
    output_filename = f"netmhcpan_result_{random_id}.txt"
    output_path = output_dir / output_filename

    # 构建命令
    cmd = [
        f"{netmhcpan_dir}/bin/netMHCpan",
        str(input_path)
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
    
    # 过滤结果
    filtered = []
    capture = False
    for line in output.splitlines():
        if "# NetMHCpan version" in line:
            capture = True
        if capture:
            filtered.append(line)

    # 写入结果文件
    with open(output_path, "w") as f:
        f.write("\n".join(filtered))

    # 错误处理
    if proc.returncode != 0:
        error_msg = stderr.decode()
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"netMHCpan执行失败: {error_msg}")

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

    result = {
        "type": "link",
        "content": file_path
    }

    return json.dumps(result, ensure_ascii=False)

@tool
def NetMHCpan(input_filecontent: str) -> str:
    """
    Use the NetMHCpan model to predict new antigens based on the input file content.
    Args:
        input_filecontent: Input the content of the file
    Return:
        result: Return the result in string format    
    """
    try:
        return asyncio.run(run_netmhcpan(input_filecontent))
    except RuntimeError as e:
        return f"调用NetMHCpan工具失败: {e}"
    except Exception as e:
        return f"调用NetMHCpan工具失败: {e}"