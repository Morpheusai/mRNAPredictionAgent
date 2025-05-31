import asyncio
import json
import os
import sys
import uuid

from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from pathlib import Path

from src.model.agents.tools.RNAFold.filter_rnafold import filter_rnafold_excel
from src.model.agents.tools.RNAFold.rnafold_to_excel import save_excel
from src.model.agents.tools.RNAPlot.rnaplot import RNAPlot
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
MINIO_BUCKET = MINIO_CONFIG["rnafold_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# netMHCpan 配置 
INPUT_TMP_DIR = CONFIG_YAML["TOOL"]["RNAFOLD"]["input_tmp_dir"]
DOWNLOADER_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["output_download_url_prefix"]
OUTPUT_TMP_DIR = CONFIG_YAML["TOOL"]["RNAFOLD"]["output_tmp_dir"]

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


async def run_rnaflod(
    input_file: str,  # MinIO 文件路径，格式为 "bucket-name/file-path"
    ) -> str:

    """
    异步运行 RNAFlod 并将处理后的结果上传到 MinIO
    :param input_file: MinIO 文件路径，格式为 "bucket-name/file-path"

    """

    minio_available = check_minio_connection()
    logger.info(f"开始处理RNAFold任务，输入文件: {input_file}")
    #提取桶名和文件
    try:
        # 去掉 minio:// 前缀
        path_without_prefix = input_file[len("minio://"):]
        
        # 找到第一个斜杠的位置，用于分割 bucket_name 和 object_name
        first_slash_index = path_without_prefix.find("/")
        
        if first_slash_index == -1:
            error_msg = f"无效的文件路径格式: {input_file}"
            logger.error(error_msg)
            raise ValueError("Invalid file path format: missing bucket name or object name")
        
        # 提取 bucket_name 和 object_name
        bucket_name = path_without_prefix[:first_slash_index]
        object_name = path_without_prefix[first_slash_index + 1:]
        
        # 打印提取结果（可选）
        # logger.info(f"Extracted bucket_name: {bucket_name}, object_name: {object_name}")
        
    except Exception as e:
        logger.error(f"Failed to parse file_path: {file_path}, error: {str(e)}")
        raise str(status_code=400, detail=f"Failed to parse file path: {str(e)}")     

    try:
        response = minio_client.get_object(bucket_name, object_name)
        file_content = response.read().decode("utf-8")
    except S3Error as e:
        error_msg = f"无法从MinIO读取文件: {str(e)}"
        logger.error(error_msg)        
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
    output_dir.mkdir(parents=True, exist_ok=True)

    # 写入输入文件
    input_path = input_dir / f"{random_id}.fasta"
    with open(input_path, "w") as f:
        f.write(file_content)

    # 构建输出文件名和临时路径
    output_filename = f"{random_id}_RNAFold_results.xlsx"
    output_path = output_dir / output_filename
    #存放输出结果的fasta的临时文件，用于给rnaplot的输入
    output_file = f"{random_id}_out.fasta"
    output_out_fsata = output_dir / output_file

    # 构建命令
    cmd = [
        "RNAfold",
        "-i", str(input_path),
        "--noPS"
    ]

    cmd2 = [
        "RNAfold",
        "-i", str(input_path),  # 输入文件
        "--auto-id",
        "--noPS"
    ]

    # 启动异步进程
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd="/mnt/softwares/ViennaRNA-2.7.0"
    )

    # 处理输出
    stdout, stderr = await proc.communicate()
    output = stdout.decode()
    
    # 错误处理
    if proc.returncode != 0:
        error_msg = f"RNAfold执行失败 | 退出码: {proc.returncode} | 错误: {stderr.decode()}"
        logger.error(error_msg)
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        output_out_fsata.unlink(missing_ok=True)
        result = {
            "type": "text",
            "content": "您的输入信息可能有误，请核对正确再试。"
        }
        return json.dumps(result, ensure_ascii=False)
    logger.info("RNAfold执行成功，正在保存结果...")
    save_excel(output, output_dir, output_filename)
    filtered_content = filter_rnafold_excel(output_path)        

    proc2 = await asyncio.create_subprocess_exec(
        *cmd2,
        stdout=asyncio.subprocess.PIPE,  # 捕获标准输出
        stderr=asyncio.subprocess.PIPE,
        cwd="/mnt/softwares/ViennaRNA-2.7.0"
    )
    stdout2, stderr2 = await proc2.communicate()
    
    if proc2.returncode != 0:
        error_msg = f"RNAfold执行失败 | 退出码: {proc.returncode} | 错误: {stderr.decode()}"
        logger.error(error_msg)
        input_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        output_out_fsata.unlink(missing_ok=True)
        result = {
            "type": "text",
            "content": "您的输入信息可能有误，请核对正确再试。"
        }    
        return json.dumps(result, ensure_ascii=False)
    
    with open(output_out_fsata, "w") as f:
        f.write(stdout2.decode())
    output_out_fsata1=("minio://molly/30aa4214-d5e7-4f6e-86d8-158c85ce6fea_3eb0579238254f51be637226a205567a_out.fsa")
    rnaplot_result = await RNAPlot.arun({"input_file" : str(output_out_fsata1)})
    rnaplot_data = json.loads(rnaplot_result)

    

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
            logger.warning("MinIO不可用，返回本地下载链接")
            file_path = f"{DOWNLOADER_PREFIX}{output_filename}"
    except S3Error as e:
        file_path = f"{DOWNLOADER_PREFIX}{output_filename}"
    finally:
        # 如果 MinIO 成功上传，清理临时文件；否则保留
        if minio_available:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
            output_out_fsata.unlink(missing_ok=True)
            logger.info("临时文件已清理")
        else:
            input_path.unlink(missing_ok=True)  # 只删除输入文件，保留输出文件
            output_out_fsata.unlink(missing_ok=True)

        writer = get_stream_writer()
        writer("#NEO#")
        writer("...工具的中间结果....")
        writer("#NEO#")

    # 处理 RNAPlot 返回的 URL
    if isinstance(rnaplot_data.get("url"), dict):
        # 情况1：RNAPlot返回的是字典（多个URL），合并成一个字典
        merged_urls = {"rnaflod_result_file_url": file_path}  # 原始 file_path
        merged_urls.update(rnaplot_data["url"])  # 合并 RNAPlot 的所有 URL
        file_path = merged_urls
    elif isinstance(rnaplot_data.get("url"), str):
        # 情况2：RNAPlot返回的是字符串（单个URL），构造字典
        file_path = {
            "original_result_file_url": file_path,
            "rnaplot_result_file_url": rnaplot_data["url"]
        }
    else:
        # 其他情况保持原样
        pass

    # 返回结果
    result = {
        "type": "link",
        "url": file_path,
        "content": filtered_content  # 替换为生成的 Markdown 内容
    }

    return json.dumps(result, ensure_ascii=False)

@tool
async def RNAFold(input_file: str) -> str:
    """                                    
    RNAFold是预测其最小自由能（MFE）二级结构，输出括号表示法和自由能值。
    Args:                                  
        input_file (str): 输入的肽段序例fasta文件路径           
    Returns:                               
        str: 返回输出括号表示法和自由能值字符串。                                                                                                                          
    """
    try:
        return await run_rnaflod(input_file)

    except Exception as e:
        result = {
            "type": "text",
            "content": f"调用RNAFold工具失败: {e}"
        }
        return json.dumps(result, ensure_ascii=False)
    
# if __name__ == "__main__":
#     input_file = "minio://molly/ab58067f-162f-49af-9d42-a61c30d227df_test_netchop.fsa"
    
#     # 最佳调用方式
#     tool_result = RNAFold.ainvoke({
#         "input_file": input_file,
#     })
#     print("工具结果:", tool_result)