import asyncio
import sys
import os
from esm.sdk import client
from esm.sdk.api import ESMProtein, GenerationConfig
import uuid
from langchain_core.tools import tool
from getpass import getpass
import json
from pathlib import Path
from minio import Minio
from minio.error import S3Error
from dotenv import load_dotenv


load_dotenv()

current_file = Path(__file__).resolve()
project_root = current_file.parents[4]  # 向上回溯 4 层目录：src/model/agents/tools → src/model/agents → src/model → src → 项目根目录
                                        
# 将项目根目录添加到 sys.path
sys.path.append(str(project_root))
from config import CONFIG_YAML

token = os.getenv("ESM_API_KEY")

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = MINIO_CONFIG["access_key"]
MINIO_SECRET_KEY = MINIO_CONFIG["secret_key"]
MINIO_BUCKET = MINIO_CONFIG["esm_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

#临时mse3输出.pdb文件
OUTPUT_TMP_DIR = CONFIG_YAML["TOOL"]["output_tmp_mse3_dir"]
DOWNLOADER_PREFIX = CONFIG_YAML["TOOL"]["output_download_url_prefix"]

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

def check_minio_connection(bucket_name=MINIO_BUCKET):
    try:
        minio_client.list_buckets()
        if not minio_client.bucket_exists(bucket_name):
            minio_client.make_bucket(bucket_name)
        return True
    except S3Error as e:
        print(f"MinIO连接或bucket操作失败: {e}")
        return False

def upload_to_minio(file_path: str, output_filename: str):
    try:
        minio_client.fput_object(
            MINIO_BUCKET,
            output_filename,
            file_path
        )
        return f"minio://{MINIO_BUCKET}/{output_filename}", None
    except S3Error as e:
        return None, f"上传 MinIO 失败: {e}"

async def run_esm3(
    protein_sequence: str,  
    model_name: str = "esm3-open-2024-03", 
    url: str = "https://forge.evolutionaryscale.ai", 
    num_steps: int = 8, 
    temperature: float = 0.7,
) -> str:
    """
    异步运行 ESM-3 进行蛋白质序列和结构预测，并上传到 MinIO。
    
    参数:
        protein_sequence (str): 需要预测的蛋白质序列。
        token (str): Forge API Token。
        model_name (str): ESM-3 模型名称。
        url (str): ESM-3 API URL。
        num_steps (int): 预测步骤数。
        temperature (float): 生成温度。

    返回:
        JSON 字符串，包含 MinIO 文件路径或下载链接。
    """

    minio_available = check_minio_connection()
    output_dir =Path(OUTPUT_TMP_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 生成随机ID和文件路径
    random_id = uuid.uuid4().hex
    output_pdb = f"esm3_result_{random_id}.pdb"
    output_path = output_dir / output_pdb

    # 连接 ESM-3 模型
    model = client(model=model_name, url=url, token=token)
    
    # 创建蛋白质对象
    protein = ESMProtein(sequence=protein_sequence)
    
    # 生成序列
    # protein = model.generate(protein, GenerationConfig(track="sequence", num_steps=num_steps, temperature=temperature))
    
    # 生成结构
    protein = model.generate(protein, GenerationConfig(track="structure", num_steps=num_steps))
    
    if not isinstance(protein, ESMProtein):
        raise RuntimeError(f"ESM-3 预测失败: {protein}")
    # 保存 PDB 文件
    protein.to_pdb(str(output_path))
    

    try:
        if minio_available:
            file_path, error = upload_to_minio(str(output_path), output_pdb)
            if error:
                file_path = f"{DOWNLOADER_PREFIX}{output_pdb}"
        else:
            file_path = f"{DOWNLOADER_PREFIX}{output_pdb}"
    except Exception as e:
        file_path = f"{DOWNLOADER_PREFIX}{output_pdb}"
    finally:
        if minio_available and file_path.startswith("minio://"):
            output_path.unlink(missing_ok=True)
    response = minio_client.get_object(MINIO_BUCKET, output_pdb)   
    file_content = response.read()
    response.close()
    response.release_conn()    
    text_content = file_content.decode("utf-8") 
    result = {
        "type": "link",
        "url": file_path,
        "content": text_content,

    }

    return json.dumps(result, ensure_ascii=False)

@tool
def ESM3(protein_sequence: str) -> str:
    """
    Use the ESM3 model to predict protein structures based on the given amino acid sequence.

    Args:
        protein_sequence (str): The amino acid sequence of the protein.

    Return:
        result (str): A JSON string containing the predicted protein structure file link.
    """
    try:
        return asyncio.run(run_esm3(protein_sequence))
    except RuntimeError as e:
        return f"调用 ESM-3 工具失败: {e}"
    except Exception as e:
        return f"调用 ESM-3 工具失败: {e}"
