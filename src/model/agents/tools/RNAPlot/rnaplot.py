# import asyncio
# import glob
# import json
# import os
# import sys
# import shutil
# import uuid

# from dotenv import load_dotenv
# from minio import Minio
# from minio.error import S3Error
# from langchain_core.tools import tool
# from pathlib import Path

# from src.utils.log import logger

# load_dotenv()
# current_file = Path(__file__).resolve()
# project_root = current_file.parents[4]  # 向上回溯 4 层目录：src/model/agents/tools → src/model/agents → src/model → src → 项目根目录
                                        
# # 将项目根目录添加到 sys.path
# sys.path.append(str(project_root))
# from config import CONFIG_YAML

# # MinIO 配置:
# MINIO_CONFIG = CONFIG_YAML["MINIO"]
# MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
# MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
# MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
# MINIO_BUCKET = MINIO_CONFIG["rnaplot_bucket"]
# MINIO_SECURE = MINIO_CONFIG.get("secure", False)

# # netMHCpan 配置 
# INPUT_TMP_DIR = CONFIG_YAML["TOOL"]["RNAPLOT"]["input_tmp_dir"]
# DOWNLOADER_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["output_download_url_prefix"]
# OUTPUT_TMP_DIR = CONFIG_YAML["TOOL"]["RNAPLOT"]["output_tmp_dir"]

# # 初始化 MinIO 客户端
# minio_client = Minio(
#     MINIO_ENDPOINT,
#     access_key=MINIO_ACCESS_KEY,
#     secret_key=MINIO_SECRET_KEY,
#     secure=MINIO_SECURE
# )
# #检查minio是否可用
# def check_minio_connection(bucket_name=MINIO_BUCKET):
#     try:
#         minio_client.list_buckets()
#         if not minio_client.bucket_exists(bucket_name):
#             minio_client.make_bucket(bucket_name)
#         return True
#     except S3Error as e:
#         print(f"MinIO连接或bucket操作失败: {e}")
#         return False


# async def run_rnaplot(
#     input_file: str,  # MinIO 文件路径，格式为 "bucket-name/file-path"
#     ) -> str:

#     """
#     异步运行 RNAPlot 并将处理后的结果上传到 MinIO
#     :param input_file: 文件路径，可以是本地路径也可以是minio路径

#     """

#     # minio_available = check_minio_connection()
#     # logger.info(f"开始处理RNAPlot任务，输入文件: {input_file}")
#     # #提取桶名和文件
#     # try:
#     #     # 去掉 minio:// 前缀
#     #     path_without_prefix = input_file[len("minio://"):]
        
#     #     # 找到第一个斜杠的位置，用于分割 bucket_name 和 object_name
#     #     first_slash_index = path_without_prefix.find("/")
        
#     #     if first_slash_index == -1:
#     #         error_msg = f"无效的文件路径格式: {input_file}"
#     #         logger.error(error_msg)
#     #         raise ValueError("Invalid file path format: missing bucket name or object name")
        
#     #     # 提取 bucket_name 和 object_name
#     #     bucket_name = path_without_prefix[:first_slash_index]
#     #     object_name = path_without_prefix[first_slash_index + 1:]
        
#     #     # 打印提取结果（可选）
#     #     # logger.info(f"Extracted bucket_name: {bucket_name}, object_name: {object_name}")
        
#     # except Exception as e:
#     #     logger.error(f"Failed to parse file_path: {file_path}, error: {str(e)}")
#     #     raise str(status_code=400, detail=f"Failed to parse file path: {str(e)}")     

#     # try:
#     #     response = minio_client.get_object(bucket_name, object_name)
#     #     file_content = response.read().decode("utf-8")
#     # except S3Error as e:
#     #     error_msg = f"无法从MinIO读取文件: {str(e)}"
#     #     logger.error(error_msg)        
#     #     return json.dumps({
#     #         "type": "text",
#     #         "content": f"无法从 MinIO 读取文件: {str(e)}"
#     #     }, ensure_ascii=False)    

#     # # 生成随机ID和文件路径
#     # random_id = uuid.uuid4().hex
#     # #base_path = Path(__file__).resolve().parents[3]  # 根据文件位置调整层级
#     # input_dir = Path(INPUT_TMP_DIR)
#     # output_dir =Path(OUTPUT_TMP_DIR)
    

#     # # 创建目录
#     # input_dir.mkdir(parents=True, exist_ok=True)
#     # output_dir.mkdir(parents=True, exist_ok=True)

#     # # 写入输入文件
#     # input_path = input_dir / f"{random_id}.fsata"
#     # with open(input_path, "w") as f:
#     #     f.write(file_content)
#     minio_available = check_minio_connection()  

#     # 判断是否为MinIO路径
#     if input_file.startswith("minio://"):
#         # MinIO路径处理
#         logger.info("检测到MinIO路径，准备从MinIO下载文件")
#         minio_available = check_minio_connection()
#         try:
#             # 解析MinIO路径
#             path_without_prefix = input_file[len("minio://"):]
#             first_slash_index = path_without_prefix.find("/")
            
#             if first_slash_index == -1:
#                 error_msg = f"MinIO路径格式错误: {input_file}"
#                 logger.error(error_msg)
#                 raise ValueError("MinIO路径格式错误: 缺少bucket名称或文件路径")
            
#             bucket_name = path_without_prefix[:first_slash_index]
#             object_name = path_without_prefix[first_slash_index + 1:]
            
#             # 从MinIO下载文件
#             response = minio_client.get_object(bucket_name, object_name)
#             file_content = response.read().decode("utf-8")
#             # 生成随机ID和文件路径
#             random_id = uuid.uuid4().hex
#             input_dir = Path(INPUT_TMP_DIR)
#             input_dir.mkdir(parents=True, exist_ok=True)
#             input_path = input_dir / f"{random_id}.fasta"

#             # 写入临时文件
#             with open(input_path, "w") as f:
#                 f.write(file_content)
                
#             logger.info(f"已从MinIO下载文件并保存到临时路径: {input_path}")
                
#         except Exception as e:
#             logger.error(f"MinIO文件处理失败: {input_file}, 错误: {str(e)}")
#             return json.dumps({
#                 "type": "text",
#                 "content": f"MinIO文件处理失败: {str(e)}"
#             }, ensure_ascii=False)
#     #兼容本地文件的输入   
#     else:
#         # 本地文件处理
#         logger.info("检测到本地文件路径，准备使用本地文件")
#         input_path = Path(input_file)
        
#         if not input_path.exists():
#             error_msg = f"本地文件不存在: {input_file}"
#             logger.error(error_msg)
#             return json.dumps({
#                 "type": "text",
#                 "content": f"本地文件不存在: {input_file}"
#             }, ensure_ascii=False)
        

    

#     # 构建输出文件名和临时路径
#     random_id = uuid.uuid4().hex
#     output_dir = Path(OUTPUT_TMP_DIR)  # 转换为 Path 对象
#     output_file = f"{random_id}_svg_file"
#     output_path = output_dir / output_file  
#     output_path.mkdir(parents=True, exist_ok=True)  # 创建目录

#     # 构建命令
#     cmd = [
#         "RNAplot",
#         "-i", str(input_path),
#         "-f", "svg"
#     ]

#     # 启动异步进程
#     proc = await asyncio.create_subprocess_exec(
#         *cmd,
#         stdout=asyncio.subprocess.PIPE,
#         stderr=asyncio.subprocess.PIPE,
#         cwd=str(output_path)
#     )

#     # 处理输出
#     stdout, stderr = await proc.communicate()
#     output = stdout.decode()
    
#     # 错误处理
#     if proc.returncode != 0:
#         error_msg = f"RNAPlot执行失败 | 退出码: {proc.returncode} | 错误: {stderr.decode()}"
#         logger.error(error_msg)
#         input_path.unlink(missing_ok=True)
#         shutil.rmtree(output_path)
#         result = {
#             "type": "text",
#             "content": "您的输入信息可能有误，请核对正确再试。"
#         }

#     # 扫描 output_path 下的所有 .svg 文件
#     svg_files = list(Path(output_path).glob("*.svg"))

#     # 构建 MinIO 上传逻辑
#     uploaded_urls = {}  # 存储所有上传成功的文件路径

#     if minio_available and svg_files:
#         for svg_file in svg_files:
#             random_id = uuid.uuid4().hex
#             try:
#                 # 在 MinIO 中的存储路径（可按需调整）
#                 minio_object_name = f"{random_id}_svg_file.svg"
                
#                 # 上传到 MinIO
#                 minio_client.fput_object(
#                     MINIO_BUCKET,
#                     minio_object_name,
#                     str(svg_file)
#                 )
                
#                 # 记录访问 URL
#                 uploaded_urls[svg_file.stem] = f"minio://{MINIO_BUCKET}/{minio_object_name}"
                
#             except S3Error as e:
#                 logger.error(f"MinIO 上传失败: {e}")
#                 uploaded_urls[svg_file.stem] = f"{DOWNLOADER_PREFIX}{svg_file.name}"

#     # 构建返回结果
#     if len(uploaded_urls) == 1:
#         file_path = list(uploaded_urls.values())[0]  # 单文件直接返回 URL
#     else:
#         file_path = uploaded_urls  # 多文件返回字典

#     result = {
#         "type": "link",
#         "url": file_path,
#         "content": "请下载以下链接查看结构图"
#     }

#     # 清理临时文件（无论是否上传成功）
#     if minio_available:
#         input_path.unlink(missing_ok=True)
#         shutil.rmtree(output_path)
#     else:
#         input_path.unlink(missing_ok=True)

#     return json.dumps(result, ensure_ascii=False)

# @tool
# async def RNAPlot(input_file: str) -> str:
#     """                                    
#     RNAPlot是用来绘制 RNA 的二级结构图。
#     Args:                                  
#         input_file (str): 输入的肽段序例fasta文件路径           
#     Returns:                               
#         str: 返回一个RNA的二级结构的矢量图的存放路径                                                                                                            
#     """
#     try:
#         return await run_rnaplot(input_file)

#     except Exception as e:
#         result = {
#             "type": "text",
#             "content": f"调用RNAPlot工具失败: {e}"
#         }
#         return json.dumps(result, ensure_ascii=False)
    
# # if __name__ == "__main__":
# #     input_file = "minio://molly/ab58067f-162f-49af-9d42-a61c30d227df_test_netchop.fsa"
    
# #     # 最佳调用方式
# #     tool_result = RNAPlot.ainvoke({
# #         "input_file": input_file,
# #     })
# #     print("工具结果:", tool_result)


import aiohttp
import asyncio
import json
import sys
import traceback

from langchain_core.tools import tool
from pathlib import Path

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]                
sys.path.append(str(project_root))
from config import CONFIG_YAML

rnaplot_url = CONFIG_YAML["TOOL"]["RNAPLOT"]["url"]

@tool
async def RNAPlot(
    input_file: str,
) -> str:
    """                                    
    RNAPlot是用来绘制 RNA 的二级结构图。
    Args:                                  
        input_file (str): 输入的肽段序例fasta文件路径           
    Returns:                               
        str: 返回一个RNA的二级结构的矢量图的存放路径                                                                                                            
    """
    
    payload = {
        "input_file": input_file,
    }

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(rnaplot_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f"调用 RNAPlot 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)