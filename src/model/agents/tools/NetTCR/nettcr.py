import asyncio
import json
import os
import sys
import shutil
import uuid


from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error
import pandas as pd 
from langchain_core.tools import tool
from pathlib import Path

from src.model.agents.tools.NetTCR.filter_nettcr import filter_nettcr_output
from src.utils.log import logger

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
MINIO_BUCKET = MINIO_CONFIG["nettcr_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# nettcr 配置 
NETTCR_DIR = CONFIG_YAML["TOOL"]["NETTCR"]["nettcr_dir"]
INPUT_TMP_DIR = CONFIG_YAML["TOOL"]["NETTCR"]["input_tmp_nettcr_dir"]
DOWNLOADER_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["output_download_url_prefix"]
OUTPUT_TMP_DIR = CONFIG_YAML["TOOL"]["NETTCR"]["output_tmp_nettcr_dir"]

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


async def run_nettcr(
    input_file: str,  # MinIO 文件路径，格式为 "bucket-name/file-path"
    nettcr_dir: str = NETTCR_DIR
    ) -> str:

    """
    异步运行 nettcr 并将处理后的结果上传到 MinIO
    :param input_file: MinIO 文件路径，格式为 "bucket-name/file-path"
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

    # 2. 从 MinIO 下载文件（二进制模式）
    try:
        response = minio_client.get_object(bucket_name, object_name)
        file_content = response.read()  # 直接读取为 bytes，不解码
    except S3Error as e:
        return json.dumps({
            "type": "text",
            "content": f"无法从 MinIO 读取文件: {str(e)}"
        }, ensure_ascii=False)

    # 生成随机ID和文件路径
    random_id = uuid.uuid4().hex
    #base_path = Path(__file__).resolve().parents[3]  # 根据文件位置调整层级
    input_dir = Path(INPUT_TMP_DIR)
    output_dir =Path(OUTPUT_TMP_DIR)
    

    # 创建目录
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)\
    
     # 获取文件扩展名
    file_ext = Path(object_name).suffix.lower()    

    # 写入输入文件
    input_path = input_dir / f"{random_id}.csv"
    # 4. 保存原始文件（根据类型处理）
    raw_input_path = input_dir / f"{random_id}_raw{file_ext}"
    with open(raw_input_path, "wb") as f:
        f.write(file_content)  # 二进制写入原始文件

    # 5. 转换为 CSV（如果是 Excel）
    input_path = input_dir / f"{random_id}.csv"
    if file_ext == ".xlsx":
        try:
            df = pd.read_excel(raw_input_path)
            df.to_csv(input_path, index=False, encoding="utf-8")
        except Exception as e:
            return json.dumps({
                "type": "text",
                "content": f"Excel 转换 CSV 失败: {str(e)}"
            }, ensure_ascii=False)
    elif file_ext == ".csv":
        try:
            # 尝试 UTF-8 解码，失败时回退到 GBK
            try:
                decoded_content = file_content.decode("utf-8")
            except UnicodeDecodeError:
                decoded_content = file_content.decode("gbk")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(decoded_content)
        except Exception as e:
            return json.dumps({
                "type": "text",
                "content": f"CSV 文件解码失败: {str(e)}"
            }, ensure_ascii=False)
    else:
        return json.dumps({
            "type": "text",
            "content": f"不支持的文件格式: {file_ext}（仅支持 .csv 或 .xlsx）"
        }, ensure_ascii=False)

    # 构建输出文件名和临时路径
    output_filename = f"{random_id}_NetTCR_results.xlsx"
    #工具输出文件路径
    output_tmp = f"{random_id}_output"
    output_tmp_path = output_dir / output_tmp
    output_tmp_path.mkdir(parents=True, exist_ok=True)
    
    # 构建命令
    cmd = [
        "python",
        "src/make_webserver_prediction.py",
        "-d", nettcr_dir,  # 添加 模型路径
        "-i", str(input_path),  # 添加 输入参数
        "-o", str(output_tmp_path),  # 添加 输出参数
        "-a", "10",  # 添加 -a 参数
    ]

    # 启动异步进程
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=f"{nettcr_dir}"
    )

    # 处理输出
    stdout, stderr = await proc.communicate()
    output = stdout.decode()
    # print(output)
       

    
    
    # 错误处理
    if proc.returncode != 0:
        error_msg = stderr.decode()
        input_path.unlink(missing_ok=True)
        shutil.rmtree(output_tmp_path, ignore_errors=True) 
        result = {
            "type": "text",
            "content": "您的输入信息可能有误，请核对正确再试。"
        }
    else:
        # 检查 CSV 文件是否存在并转换
        csv_file = output_tmp_path / "nettcr_predictions.csv"
        excel_file = output_tmp_path / "nettcr_predictions.xlsx"
        
        try:
            df = pd.read_csv(csv_file)
            df.to_excel(excel_file, index=False, engine="openpyxl")
        except FileNotFoundError:
            logger.error(f"警告: 未找到预测结果文件 {csv_file}")
            return json.dumps({
                "type": "text",
                "content": f"警告: 未找到预测结果文件 {csv_file}"
            }, ensure_ascii=False)            
        except Exception as e:
            logger.error(f"CSV 转 Excel 失败: {str(e)}")    
            return json.dumps({
                "type": "text",
                "content": f"CSV 转 Excel 失败: {str(e)}"
            }, ensure_ascii=False)  

        # 调用markdown过滤函数
        filtered_content = filter_nettcr_output(excel_file)
        try:
            if minio_available:
                minio_client.fput_object(
                    MINIO_BUCKET,
                    output_filename,
                    str(excel_file)
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
                shutil.rmtree(output_tmp_path, ignore_errors=True) 
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
def NetTCR(input_file: str) -> str:
    """                                    
    NetTCR用于预测肽段（peptide）与 T 细胞受体（TCR）的相互作用。
    Args:                                  
        input_file (str): 输入文件的路径，文件需包含待预测的肽段和 TCR 序列。
    Returns:                               
        str: 返回高结合亲和力的肽段序例信息                                                                                                                           
    """
    try:
        return asyncio.run(run_nettcr(input_file))

    except Exception as e:
        result = {
            "type": "text",
            "content": f"调用NetTCR工具失败: {e}"
        }
        return json.dumps(result, ensure_ascii=False)
    
    
