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
import pandas as pd
from io import BytesIO
from typing import List, Dict, Optional, Union

from src.model.agents.tools.NetChop.netchop import NetChop
from src.model.agents.tools.CleavagePeptide.cleavage_peptide import NetChop_Cleavage
from src.model.agents.tools.NetMHCPan.netmhcpan import NetMHCpan
from src.model.agents.tools.BigMHC.bigmhc import BigMHC_EL,BigMHC_IM
from src.model.agents.tools.PMTNet.pMTnet import pMTnet
from src.model.agents.tools.NetTCR.nettcr import NetTCR


load_dotenv()
current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML

# MinIO 配置:
MINIO_CONFIG = CONFIG_YAML["MINIO"]
MINIO_ENDPOINT = MINIO_CONFIG["endpoint"]
MINIO_ACCESS_KEY = os.getenv("ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("SECRET_KEY")
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
BIND_LEVEL_ALTERNATIVE = NEOANTIGEN_CONFIG["bind_level_alternative"]  
BIGMHC_EL_THRESHOLD = NEOANTIGEN_CONFIG["bigmhc_el_threshold"]
BIGMHC_IM_THRESHOLD = NEOANTIGEN_CONFIG["bigmhc_im_threshold"]

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)

async def run_neoanigenselection(
    input_file: str,  # MinIO 文件路径，格式为 "bucket-name/file-path"
    mhc_allele: Optional[List[str]] ,  # mhc分型
    cdr3_sequence: Optional[List[str]]    #CDR3序列数据
    ) -> str:
    # 初始化变量
    netchop_result_file_path = None
    cleavage_result_file_path = None
    netmhcpan_result_file_path = None
    bigmhc_el_result_file_path = None
    bigmhc_im_result_file_path = None
    pmtnet_result_file_path = None
    nettcr_result_file_path = None

#第一步：蛋白切割位点预测
    netchop_result = await NetChop.arun({"input_file" : input_file,"cleavage_site_threshold" : 0.5})

    # 解析NetChop结果
    try:
        netchop_result_dict = json.loads(netchop_result)
    except json.JSONDecodeError:
        return json.dumps({"type": "text", "content": "蛋白切割位点阶段NetChop工具执行失败"}, ensure_ascii=False)

    # 检查NetChop是否成功
    if netchop_result_dict.get("type") != "link":
        # 直接返回NetChop的错误信息
        return netchop_result
    netchop_result_file_path=netchop_result_dict["url"]
    #对netchop结果获取肽段fasta文件
    netchop_cleavage_result = await NetChop_Cleavage.arun({"input_file":netchop_result_file_path})

    # 解析Cleavage结果
    try:
        cleavage_result_dict = json.loads(netchop_cleavage_result)
    except json.JSONDecodeError:
        return json.dumps({"type": "text", "content": "蛋白切割位点阶段NetChop_Cleavage工具执行失败"}, ensure_ascii=False)

    # 检查最终结果是否包含有效文件
    if cleavage_result_dict.get("type") == "link":
        
        # 验证文件是否为空
        cleavage_result_file_path = cleavage_result_dict["url"]
        try:
            # 从MinIO获取文件元数据
            path_without_prefix = cleavage_result_file_path[len("minio://"):]
            bucket_name, object_name = path_without_prefix.split("/", 1)
            stat = minio_client.stat_object(bucket_name, object_name)
            
            if stat.size == 0:  # 文件大小为0
                return json.dumps({
                    "type": "text",
                    "content": "蛋白切割位点阶段未找到符合长度和剪切条件的肽段"
                }, ensure_ascii=False)
        except S3Error as e:
            return json.dumps({
                "type": "text",
                "content": f"蛋白切割位点阶段NetChop_Cleavage工具执行失败: {str(e)}"
            }, ensure_ascii=False)    
        
    # 检查是否成功获取文件路径
    if not cleavage_result_file_path:
        return json.dumps({
            "type": "text",
            "content": "蛋白切割位点阶段未生成有效结果文件"
        }, ensure_ascii=False)        
        #################下载cleavage_result_file_path文件
            # print(cleavage_result_file_path)
            # # 解析MinIO路径
            # try:
            #     path_without_prefix = cleavage_result_file_path[len("minio://"):]
            #     bucket_name, object_name = path_without_prefix.split("/", 1)
            #     print(f"解析成功 - 桶: {bucket_name}, 文件: {object_name}")
            # except Exception as e:
            #     print(f"路径解析失败: {str(e)}")
            #     raise  # 或者使用 sys.exit(1) 直接退出

            # # 下载并保存文件
            # try:
            #     debug_path = f"/tmp/{object_name}"
                
            #     # 使用更高效的 fget_object 直接保存到本地
            #     minio_client.fget_object(bucket_name, object_name, debug_path)
                
            #     # 验证文件
            #     if os.path.exists(debug_path):
            #         file_size = os.path.getsize(debug_path)
            #         print(f"文件已保存到 {debug_path} (大小: {file_size}字节)")
            #     else:
            #         print("警告: 文件保存后验证失败")

            # except Exception as e:
            #     import traceback
            #     print(f"文件下载失败: {str(e)}")
            #     traceback.print_exc()  



#第二步：pMHC结合亲和力预测
    # cleavage_result_file_path="minio://molly/f0e5822c-0c0b-4cb6-95f2-07ec51730ba6_test.fsa"
    mhc_allele_str = ",".join(mhc_allele) 
    netmhcpan_result = await NetMHCpan.arun({"input_file" : cleavage_result_file_path,"mhc_allele" : mhc_allele_str})
    try:
        netmhcpan_result_dict = json.loads(netmhcpan_result)
    except json.JSONDecodeError:
        return json.dumps({"type": "link", 
                           "url":{"result_file_url": cleavage_result_file_path,  },
                           "content": f"蛋白切割位点预测阶段文件以生成，请下载cleavage_result.fasta文件查看\npMHC结合亲和力预测阶段NetMHCpan工具执行失败"}, ensure_ascii=False)
    
    # 检查NetMHCpan是否成功
    if netmhcpan_result_dict.get("type") != "link":
        # 直接返回NetMHCpan的错误信息
        # return netmhcpan_result
        return json.dumps({"type": "link", 
                           "url":{"result_file_url": cleavage_result_file_path,  },
                           "content": f"蛋白切割位点预测阶段文件以生成，请下载cleavage_result.fasta文件查看\npMHC结合亲和力预测阶段未成功运行，{netmhcpan_result_dict['content']}"}, ensure_ascii=False)
        
    #获取肽段
    netmhcpan_result_file_path = netmhcpan_result_dict["url"]
# ########下载netmhcpan_result_file_path文件
#     # 解析MinIO路径
#     try:
#         path_without_prefix = netmhcpan_result_file_path[len("minio://"):]
#         first_slash_index = path_without_prefix.find("/")
        
#         if first_slash_index == -1:
#             raise ValueError("Invalid file path format")
        
#         bucket_name = path_without_prefix[:first_slash_index]
#         object_name = path_without_prefix[first_slash_index + 1:]
#         print(f"MinIO路径解析成功 - 桶名: {bucket_name}, 对象名: {object_name}")
#     except Exception as e:
#         print(f"MinIO路径解析失败: {str(e)}")
#         return json.dumps({
#             "type": "link", 
#             "url": {"result_file_url": cleavage_result_file_path},
#             "content": "蛋白切割位点预测阶段文件已生成\npMHC结合亲和力预测文件路径解析失败"
#         }, ensure_ascii=False)

#     # 下载并处理Excel文件
#     try:
#         # 下载文件
#         response = minio_client.get_object(bucket_name, object_name)
#         file_data = response.read()
        
#         # 验证文件内容
#         if len(file_data) < 100:  # Excel文件通常大于100字节
#             raise ValueError("文件大小异常，可能下载不完整")
        
#         # 保存原始文件用于调试
#         debug_path = f"/tmp/{object_name}"
#         with open(debug_path, 'wb') as f:
#             f.write(file_data)
#         print(f"已保存原始文件到 {debug_path}")
        
#         # 尝试读取Excel
#         excel_data = BytesIO(file_data)
#         try:
#             df = pd.read_excel(excel_data, engine='openpyxl')
#         except Exception as e:
#             excel_data.seek(0)
#             try:
#                 df = pd.read_excel(excel_data, engine='xlrd')
#             except:
#                 raise ValueError(f"无法用任何引擎读取Excel: {str(e)}")
                
#         print(f"成功读取Excel，共{len(df)}行数据")
        
#     except Exception as e:
#         print(f"文件处理失败: {str(e)}")
#         return json.dumps({
#             "type": "link",
#             "url": {"result_file_url": cleavage_result_file_path},
#             "content": f"蛋白切割位点预测阶段文件已生成\npMHC结合亲和力预测文件处理失败: {str(e)}"
#         }, ensure_ascii=False)
        #提取桶名和文件
    try:
        # 去掉 minio:// 前缀
        path_without_prefix = netmhcpan_result_file_path[len("minio://"):]
        
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
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)  
    except S3Error as e:
        # return json.dumps({
        #     "type": "text",
        #     "content": f"无法从 MinIO 读取文件: {str(e)}"
        # }, ensure_ascii=False)       
        return json.dumps({"type": "link", 
                           "url":{"result_file_url": cleavage_result_file_path,},
                           "content": f"蛋白切割位点预测阶段文件以生成，请下载cleavage_result.fasta文件查看\npMHC结合亲和力预测阶段未成功运行，无法从 MinIO 读取文件: {str(e)}"}, 
                           ensure_ascii=False)
    # 筛选BindLevel为SB的行
    # sb_peptides = df[df['BindLevel'].str.strip().isin(['<= SB', '<= WB'])]
    sb_peptides = df[df['BindLevel'].str.strip().isin(BIND_LEVEL_ALTERNATIVE)]

    # 检查是否存在SB肽段
    if sb_peptides.empty:
        # return json.dumps({
        #     "type": "text",
        #     "content": "pMHC结合亲和力预测NetMHCpan工具未找到高亲和力肽段"
        # }, ensure_ascii=False)    
        return json.dumps({"type": "link", 
                    "url":{"result_file_url": cleavage_result_file_path,},
                    "content": f"蛋白切割位点预测阶段文件以生成，请下载cleavage_result.fasta文件查看\npMHC结合亲和力预测阶段结束，NetMHCpan工具未找到高亲和力肽段"}, 
                    ensure_ascii=False)

    # 创建FASTA内容
    fasta_content = []
    for idx, row in sb_peptides.iterrows():
        # 从Identity列提取信息作为描述
        identity = row['Identity']
        peptide = row['Peptide']
        
        # 创建FASTA条目
        fasta_content.append(f">{identity}")
        fasta_content.append(peptide)

    # 合并为完整的FASTA字符串
    fasta_str = "\n".join(fasta_content)

    # 生成UUID文件名
    uuid_name = str(uuid.uuid4())
    netmhcpan_result_fasta_filename = f"{uuid_name}_netmhcpan.fasta"

    # 将FASTA文件上传到MinIO的molly桶
    try:
        fasta_bytes = fasta_str.encode('utf-8')
        fasta_stream = BytesIO(fasta_bytes)
        minio_client.put_object(
            "molly",
            netmhcpan_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
        # logger.info(f"FASTA文件已成功上传到: minio://molly/{fasta_filename}")
    except Exception as e:
        # logger.error(f"上传FASTA文件到MinIO失败: {e}")
        raise

    netmhcpan_result_file_path = f"minio://molly/{netmhcpan_result_fasta_filename}"
    #传入辅助模型进行选择阳性肽段
    bigmhc_el_result = await BigMHC_EL.arun({"peptide_input": netmhcpan_result_file_path,"hla_input":mhc_allele})  #TODO 修改

    try:
        # 解析返回的JSON结果
        bigmhc_el_result_dict = json.loads(bigmhc_el_result)
    except json.JSONDecodeError:
        # return json.dumps({"type": "text", "content": "pMHC结合亲和力预测阶段BigMHC_el工具执行失败"}, ensure_ascii=False)
        return json.dumps({"type": "link", 
                           "url":{"result_file_url": cleavage_result_file_path,  },
                           "content": f"蛋白切割位点预测阶段文件以生成，请下载cleavage_result.fasta文件查看\npMHC结合亲和力预测阶段BigMHC_el工具执行失败"}, ensure_ascii=False)
    # 检查工具是否执行成功
    if bigmhc_el_result_dict.get("type") != "link":
        # return bigmhc_el_result
        return json.dumps({"type": "link", 
                           "url":{"result_file_url": cleavage_result_file_path,  },
                           "content": f"蛋白切割位点预测阶段文件以生成，请下载cleavage_result.fasta文件查看\npMHC结合亲和力预测阶段未成功运行，{bigmhc_el_result_dict['content']}"}, 
                           ensure_ascii=False)
            

    # 获取结果文件路径
    bigmhc_el_result_file_path = bigmhc_el_result_dict["url"]

    # 解析MinIO文件路径，提取桶名和文件名
    try:
        # 去掉minio://前缀
        path_without_prefix = bigmhc_el_result_file_path[len("minio://"):]
        
        # 找到第一个斜杠位置，分割桶名和文件名
        first_slash_index = path_without_prefix.find("/")
        
        if first_slash_index == -1:
            raise ValueError("文件路径格式错误：缺少桶名或文件名")
        
        bucket_name = path_without_prefix[:first_slash_index]
        object_name = path_without_prefix[first_slash_index + 1:]
        
    except Exception as e:
        raise str(status_code=400, detail=f"解析文件路径失败: {str(e)}") 

    # 从MinIO读取Excel文件
    try:
        response = minio_client.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)  
    except S3Error as e:
        # return json.dumps({
        #     "type": "text",
        #     "content": f"无法从MinIO读取文件: {str(e)}"
        # }, ensure_ascii=False)      
        return json.dumps({"type": "link", 
                           "url":{"result_file_url": cleavage_result_file_path,},
                           "content": f"蛋白切割位点预测阶段文件以生成，请下载cleavage_result.fasta文件查看\npMHC结合亲和力预测阶段未成功运行，无法从 MinIO 读取文件: {str(e)}"}, 
                           ensure_ascii=False)     

    # 筛选BigMHC_EL值≥0.5的行
    high_affinity_peptides = df[df['BigMHC_EL'] >= BIGMHC_EL_THRESHOLD]

    # 检查是否存在高亲和力肽段
    if high_affinity_peptides.empty:
        # return json.dumps({
        #     "type": "text",
        #     "content": "未找到高亲和力肽段(BigMHC_EL ≥ 0.5)"
        # }, ensure_ascii=False)    
        return json.dumps({"type": "link", 
                    "url":{"result_file_url": cleavage_result_file_path,},
                    "content": f"蛋白切割位点预测阶段文件以生成，请下载cleavage_result.fasta文件查看\npMHC结合亲和力预测阶段结束，BigMHC工具未找到高亲和力肽段(BigMHC_EL ≥ {BIGMHC_EL_THRESHOLD})"}, 
                    ensure_ascii=False)
    # 构建FASTA文件内容
    fasta_content = []
    for idx, row in high_affinity_peptides.iterrows():
        # 获取肽段序列和MHC等位基因
        peptide = row['pep']
        mhc_allele = row['mhc']

        # 标准化MHC等位基因格式（确保HLA-后字母后有*）
        if 'HLA-' in mhc_allele and '*' not in mhc_allele.split('HLA-')[1][:2]:
            # 在HLA-后的第一个字母后插入*
            parts = mhc_allele.split('HLA-')
            if len(parts) > 1:
                allele_part = parts[1]
                if len(allele_part) > 1 and allele_part[1].isdigit():  # 类似A02:01的情况
                    mhc_allele = f"HLA-{allele_part[0]}*{allele_part[1:]}"
        
        # 创建FASTA条目，格式为：>肽段序列|MHC等位基因
        fasta_content.append(f">{peptide}|{mhc_allele}")
        fasta_content.append(peptide)

    # 合并为完整的FASTA字符串
    fasta_str = "\n".join(fasta_content)

    # 生成唯一的文件名
    uuid_name = str(uuid.uuid4())
    bigmhc_el_result_fasta_filename = f"{uuid_name}_bigmhc_el.fasta"

    # 将FASTA文件上传到MinIO的molly桶
    try:
        fasta_bytes = fasta_str.encode('utf-8')
        fasta_stream = BytesIO(fasta_bytes)
        minio_client.put_object(
            "molly",
            bigmhc_el_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
    except Exception as e:
        raise 
    bigmhc_el_result_file_path = f"minio://molly/{bigmhc_el_result_fasta_filename}"
#第三步 pMHC免疫原性预测
    bigmhc_im_result = await BigMHC_IM.arun({"input_file": bigmhc_el_result_file_path})  #TODO 修改

    try:
        # 解析返回的JSON结果
        bigmhc_im_result_dict = json.loads(bigmhc_im_result)
    except json.JSONDecodeError:
        # return json.dumps({"type": "text", "content": "pMHC免疫原性预测阶段BigMHC_im工具执行失败"}, ensure_ascii=False)
        return json.dumps({"type": "link", 
                        "url": {
                            "cleavage_result_result_file_url": cleavage_result_file_path, 
                            "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                        },
                        "content": (
                            f"蛋白切割位点预测阶段文件以生成，请下载cleavage_result.fasta文件查看。\n"
                            f"pMHC结合亲和力预测阶段文件以生成，请下载bigmhc_el.fasta文件查看。\n"
                            f"pMHC免疫原性预测阶段BigMHC_im工具执行失败"
                        )}, ensure_ascii=False) 

    # 检查工具是否执行成功
    if bigmhc_im_result_dict.get("type") != "link":
        # return bigmhc_im_result
        return json.dumps(
            {
                "type": "link",
                "url": {
                    "cleavage_result_result_file_url": cleavage_result_file_path,
                    "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                },
                "content": (
                    f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                    f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                    f"pMHC免疫原性预测阶段未能成功运行，{bigmhc_im_result_dict['content']}"
                ),
            },
            ensure_ascii=False,
        )    

    # 获取结果文件路径
    bigmhc_im_result_file_path = bigmhc_im_result_dict["url"]

    # 解析MinIO文件路径，提取桶名和文件名
    try:
        # 去掉minio://前缀
        path_without_prefix = bigmhc_im_result_file_path[len("minio://"):]
        
        # 找到第一个斜杠位置，分割桶名和文件名
        first_slash_index = path_without_prefix.find("/")
        
        if first_slash_index == -1:
            raise ValueError("文件路径格式错误：缺少桶名或文件名")
        
        bucket_name = path_without_prefix[:first_slash_index]
        object_name = path_without_prefix[first_slash_index + 1:]
        
    except Exception as e:
        raise str(status_code=400, detail=f"解析文件路径失败: {str(e)}") 

    # 从MinIO读取Excel文件
    try:
        response = minio_client.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)  
    except S3Error as e:
        # return json.dumps({
        #     "type": "text",
        #     "content": f"无法从MinIO读取文件: {str(e)}"
        # }, ensure_ascii=False)        
        return json.dumps(
            {
                "type": "link",
                "url": {
                    "cleavage_result_result_file_url": cleavage_result_file_path,
                    "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                },
                "content": (
                    f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                    f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                    f"pMHC免疫原性预测阶段未能成功运行，无法从 MinIO 读取文件: {str(e)}"
                ),
            },
            ensure_ascii=False,
        )         

    # 筛选BigMHC_IM值≥0.6的行
    high_affinity_peptides = df[df['BigMHC_IM'] >= BIGMHC_IM_THRESHOLD]

    # 检查是否存在高亲和力肽段
    if high_affinity_peptides.empty:
        # return json.dumps({
        #     "type": "text",
        #     "content": "未找到高免疫原性肽段(BigMHC_IM ≥ 0.6)"
        # }, ensure_ascii=False)    
        return json.dumps(
            {
                "type": "link",
                "url": {
                    "cleavage_result_result_file_url": cleavage_result_file_path,
                    "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                },
                "content": (
                    f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                    f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                    f"pMHC免疫原性预测阶段未能成功运行，未找到高免疫原性肽段(BigMHC_IM ≥ {BIGMHC_IM_THRESHOLD})"
                ),
            },
            ensure_ascii=False,
        )       

    # 构建FASTA文件内容
    fasta_content = []
    for idx, row in high_affinity_peptides.iterrows():
        # 获取肽段序列和MHC等位基因
        peptide = row['pep']
        mhc_allele = row['mhc']
        
        # 创建FASTA条目，格式为：>肽段序列|MHC等位基因
        fasta_content.append(f">{peptide}|{mhc_allele}")
        fasta_content.append(peptide)

    # 合并为完整的FASTA字符串
    fasta_str = "\n".join(fasta_content)

    # 生成唯一的文件名
    uuid_name = str(uuid.uuid4())
    bigmhc_im_result_fasta_filename = f"{uuid_name}_bigmhc_im.fasta"

    # 将FASTA文件上传到MinIO的molly桶
    try:
        fasta_bytes = fasta_str.encode('utf-8')
        fasta_stream = BytesIO(fasta_bytes)
        minio_client.put_object(
            "molly",
            bigmhc_im_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
    except Exception as e:
        raise 
    bigmhc_im_result_file_path = f"minio://molly/{bigmhc_im_result_fasta_filename}"

#第四步 pMHC-TCR相互作用预测
    if cdr3_sequence == None:
        # result = {
        #     "type": "link",
        #     "url": bigmhc_im_result_file_path,
        #     "content": "提供的下载下载链接是筛选到合适的肽段以及对应的HLA分型"  # 替换为生成的 Markdown 内容
        # }
        # return json.dumps(result, ensure_ascii=False)
    
        return json.dumps(
            {
                "type": "link",
                "url": {
                    "cleavage_result_result_file_url": cleavage_result_file_path,
                    "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                    "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                },
                "content": (
                    f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                    f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                    f"pMHC免疫原性预测阶段文件已生成，请下载 bigmhc_im.fasta 文件查看。\n"
                    f"未提供cdr3序列无法进行下一步pMHC-TCR相互作用预测"
                ),
            },
            ensure_ascii=False,
        )           
    else:
        # tmp_file_path="minio://molly/66dd7c86-f1c4-455e-9e50-3b2a77be66c9_test_input.csv"
        pmtnet_result = await pMTnet.arun({"cdr3_list":cdr3_sequence,"uploaded_file": bigmhc_im_result_file_path})  #TODO 修改
        try:
            # 解析返回的JSON结果
            pmtnet_result_dict = json.loads(pmtnet_result)
            
        except json.JSONDecodeError:
            # return json.dumps({"type": "text", "content": "pMHC-TCR相互作用预测阶段pMTnet工具执行失败"}, ensure_ascii=False)
            return json.dumps(
                {
                    "type": "link",
                    "url": {
                        "cleavage_result_result_file_url": cleavage_result_file_path,
                        "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                        "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                    },
                    "content": (
                        f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                        f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                        f"pMHC免疫原性预测阶段文件已生成，请下载 bigmhc_im.fasta 文件查看。\n"
                        f"pMHC-TCR相互作用预测阶段未完成，pMTnet工具执行失败"
                    ),
                },
                ensure_ascii=False,
            )         

        # 检查工具是否执行成功
        if pmtnet_result_dict.get("type") != "link":
            # return pmtnet_result_dict
            return json.dumps(
                {
                    "type": "link",
                    "url": {
                        "cleavage_result_result_file_url": cleavage_result_file_path,
                        "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                        "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                    },
                    "content": (
                        f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                        f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                        f"pMHC免疫原性预测阶段文件已生成，请下载 bigmhc_im.fasta 文件查看。\n"
                        f"pMHC-TCR相互作用预测阶段未成功运行，{pmtnet_result_dict['content']}"
                    ),
                },
                ensure_ascii=False,
            )                   
    pmtnet_result_file_path = pmtnet_result_dict["url"]
    if cdr3_sequence != "complete":
        # return pmtnet_result_dict
        return json.dumps(
            {
                "type": "link",
                "url": {
                    "cleavage_result_result_file_url": cleavage_result_file_path,
                    "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                    "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                    "pmtnet_result_file_url": pmtnet_result_file_path,
                },
                "content": (
                    f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                    f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                    f"pMHC免疫原性预测阶段文件已生成，请下载 bigmhc_im.fasta 文件查看。\n"
                    f"pMHC-TCR相互作用预测文件已生成,请下载pMTnet_results.csv文件根据需求选择rank值对应的肽段，rank值越大，结合力越强。\n"
                    f"未提供完整的cdr3序列无法更进一步精准的进行下一步pMHC-TCR相互作用预测\n"
                ),
            },
            ensure_ascii=False,
        )       
    else:
        tmp_file_path="minio://molly/5a9592bd-4bcf-4d09-a8d2-ca590a1f6515_small_example.csv"
        nettcr_result = await NetTCR.arun({"input_file": tmp_file_path})  #TODO 修改
        try:
            # 解析返回的JSON结果
            nettcr_result_dict = json.loads(nettcr_result)
            
        except json.JSONDecodeError:
            # return json.dumps({"type": "text", "content": "pMHC-TCR相互作用预测阶段NetTCR工具执行失败"}, ensure_ascii=False)
            return json.dumps(
                {
                    "type": "link",
                    "url": {
                        "cleavage_result_result_file_url": cleavage_result_file_path,
                        "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                        "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                        "pmtnet_result_file_url": pmtnet_result_file_path,                        
                    },
                    "content": (
                        f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                        f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                        f"pMHC-TCR相互作用预测文件已生成,请下载pMTnet_results.csv文件根据需求选择rank值对应的肽段，rank值越大，结合力越强。\n"
                        f"精准pMHC-TCR相互作用预测阶段未完成，NetTCR工具执行失败"
                    ),
                },
                ensure_ascii=False,
            )         
        

        # 检查工具是否执行成功
        if nettcr_result_dict.get("type") != "link":
            # return nettcr_result_dict 
            return json.dumps(
                {
                    "type": "link",
                    "url": {
                        "cleavage_result_result_file_url": cleavage_result_file_path,
                        "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                        "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                        "pmtnet_result_file_url": pmtnet_result_file_path,                        
                    },
                    "content": (
                        f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                        f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                        f"pMHC-TCR相互作用预测文件已生成,请下载pMTnet_results.csv文件根据需求选择rank值对应的肽段，rank值越大，结合力越强。\n"
                        f"精准pMHC-TCR相互作用预测阶段未成功运行，{nettcr_result_dict['content']}"
                    ),
                },
                ensure_ascii=False,
            )                    
        nettcr_result_file_path = nettcr_result_dict["url"]
        return json.dumps(
            {
                "type": "link",
                "url": {
                    "cleavage_result_result_file_url": cleavage_result_file_path,
                    "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                    "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                    "pmtnet_result_file_url": pmtnet_result_file_path,
                    "nettcr_result_file_url": nettcr_result_file_path
                },
                "content": (
                    f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                    f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                    f"pMHC免疫原性预测阶段文件已生成，请下载 bigmhc_im.fasta 文件查看。\n"
                    f"pMHC-TCR相互作用预测文件已生成,请下载pMTnet_results.csv文件根据需求选择rank值对应的肽段，rank值越大，结合力越强。\n"
                    f"精准pMHC-TCR相互作用预测文件已生成，请下载 NetTCR_results.xlsx 文件根据需求选择rank值对应的肽段，rank值越大，结合力越强。\n"
                ),
            },
            ensure_ascii=False,
        )        


@tool
def NeoAntigenSelection(input_file: str,mhc_allele: Optional[List[str]] = None, cdr3_sequence: Optional[List[str]] = None) -> str:
    """                                    
    NeoAntigenSelection是基于用户输入的患者信息，结合已有的工具库，完成个体化neo-antigen筛选，并辅助后续的mRNA疫苗设计。  工具。
    Args:                                  
        input_file (str): 输入的肽段序例fasta文件路径           
        mhc_allele (Optional[Union[List[str], str]]): MHC比对的等位基因。
        cdr3_sequence (Optional[List[str]]):  cdr3序列。
    Returns:                               
        str: 返回高结合亲和力的肽段序例信息                                                                                                                           
    """
    try:
        return asyncio.run(run_neoanigenselection(input_file,mhc_allele,cdr3_sequence))

    except Exception as e:
        result = {
            "type": "text",
            "content": f"调用NeoAntigenSelection工具失败: {e}"
        }
        return json.dumps(result, ensure_ascii=False)
    
if __name__ == "__main__":
    input_file = "minio://molly/ab58067f-162f-49af-9d42-a61c30d227df_test_netchop.fsa"
    
    # 最佳调用方式
    tool_result = NeoAntigenSelection.invoke({
        "input_file": input_file,
        "mhc_allele": ["HLA-A02:01"],
        "cdr3_sequence": ["CASSVASSGNIQYF"]
    })
    print("工具结果:", tool_result)