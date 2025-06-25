# import asyncio
# import json
# import os
# import uuid

# from dotenv import load_dotenv
# from esm.sdk import client
# from esm.sdk.api import ESMProtein, GenerationConfig
# from langchain_core.tools import tool
# from pathlib import Path


# from config import CONFIG_YAML
# from src.utils.minio_utils import upload_file_to_minio
# from src.utils.log import logger


# load_dotenv()

# TOKEN = os.getenv("ESM_API_KEY")

# # MinIO 配置:
# MINIO_CONFIG = CONFIG_YAML["MINIO"]
# MINIO_BUCKET = MINIO_CONFIG["esm_bucket"]

# #临时mse3输出.pdb文件
# OUTPUT_TMP_DIR = CONFIG_YAML["TOOL"]["ESM"]["output_tmp_mse3_dir"]
# DOWNLOADER_PREFIX = CONFIG_YAML["TOOL"]["COMMON"]["output_download_url_prefix"]


# async def run_esm3(
#     protein_sequence: str,  
#     model_name: str = "esm3-open-2024-03", 
#     url: str = "https://forge.evolutionaryscale.ai", 
#     num_steps: int = 8, 
#     temperature: float = 0.7,
# ) -> str:
#     """
#     异步运行 ESM-3 进行蛋白质序列和结构预测，并上传到 MinIO。
    
#     参数:
#         protein_sequence (str): 需要预测的蛋白质序列。
#         token (str): Forge API Token。
#         model_name (str): ESM-3 模型名称。
#         url (str): ESM-3 API URL。
#         num_steps (int): 预测步骤数。
#         temperature (float): 生成温度。

#     返回:
#         JSON 字符串，包含 MinIO 文件路径或下载链接。
#     """

#     output_dir =Path(OUTPUT_TMP_DIR)
#     output_dir.mkdir(parents=True, exist_ok=True)

#     # 生成随机ID和文件路径
#     random_id = uuid.uuid4().hex
#     output_pdb = f"{random_id}_ESM3_results.pdb"
#     output_path = output_dir / output_pdb

#     # 连接 ESM-3 模型
#     model = client(model=model_name, url=url, token=TOKEN)
    
#     # 创建蛋白质对象
#     protein = ESMProtein(sequence=protein_sequence)
    
#     # 生成序列
#     # protein = model.generate(protein, GenerationConfig(track="sequence", num_steps=num_steps, temperature=temperature))
    
#     # 生成结构
#     protein = model.generate(protein, GenerationConfig(track="structure", num_steps=num_steps))
    
#     if not isinstance(protein, ESMProtein):
#         return json.dumps({
#             "type": "text",
#             "content": f"ESM-3 预测失败: {str(protein)}"
#             }, ensure_ascii=False) 
#     # 保存 PDB 文件
#     protein.to_pdb(str(output_path))
    

#     try:
#         file_path=upload_file_to_minio(str(output_path),MINIO_BUCKET,output_pdb)

#     except Exception as e:
#         logger.error(f"An unexpected error occurred: {e}")
#         raise
#     finally:
#         output_path.unlink(missing_ok=True)
            
#     # response = minio_client.get_object(MINIO_BUCKET, output_pdb)   
#     # file_content = response.read()
#     # response.close()
#     # response.release_conn()    
#     # text_content = file_content.decode("utf-8") 
#     text_content="已完成肽段序列的三维结构预测，并生成输出 PDB 文件。"
#     result = {
#         "type": "link",
#         "url": file_path,
#         "content": text_content,
#     }

#     return json.dumps(result, ensure_ascii=False)

# @tool
# def ESM3(protein_sequence: str) -> str:
#     """ 
#     ESM3用于预测输入肽段序例的三维结构，并生成pdb文件。
#     Args:
#         protein_sequence (str): 输入预测的肽段序例
                                                                                                                                                                           
#     Return:
#         result (str): 返回生成的pdb文件信息
#     """
#     try:
#         return asyncio.run(run_esm3(protein_sequence))
#     except Exception as e:
#         result = {
#             "type": "text",
#             "content": f"调用NetMHCpan工具失败: {e}"
#         }
#         return json.dumps(result, ensure_ascii=False)
