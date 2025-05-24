import asyncio
import json
import os
import sys
import uuid

from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langchain_core.runnables import RunnableSerializable,RunnableLambda
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from pathlib import Path
import pandas as pd
from io import BytesIO
from typing import List, Dict, Optional, Union, AsyncIterator,Any

from src.model.agents.core import get_model
from src.model.agents.core.tool_summary_prompts import (
    NETMHCPAN_PROMPT,
    BIGMHC_EL_PROMPT,
    BIGMHC_IM_PROMPT,
    RNAFOLD_PROMPT,
    PMTNET_PROMPT
)
from src.model.schema.models import FileDescriptionName
from src.model.agents.tools.NetChop.netchop import NetChop
from src.model.agents.tools.CleavagePeptide.cleavage_peptide import NetChop_Cleavage
from src.model.agents.tools.NetMHCPan.netmhcpan import NetMHCpan
from src.model.agents.tools.BigMHC.bigmhc import BigMHC_EL,BigMHC_IM
from src.model.agents.tools.PMTNet.pMTnet import pMTnet
from src.model.agents.tools.NetTCR.nettcr import NetTCR
from src.model.agents.tools.NeoMRNASelection.cds_combine import concatenate_peptides_with_linker
from src.model.agents.tools.NeoMRNASelection.utr_spacer_rnafold import utr_spacer_rnafold_to_mrna


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
MOLLY_BUCKET = MINIO_CONFIG["molly_bucket"]
MINIO_SECURE = MINIO_CONFIG.get("secure", False)

NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
BIND_LEVEL_ALTERNATIVE = NEOANTIGEN_CONFIG["bind_level_alternative"]  
BIGMHC_EL_THRESHOLD = NEOANTIGEN_CONFIG["bigmhc_el_threshold"]
BIGMHC_IM_THRESHOLD = NEOANTIGEN_CONFIG["bigmhc_im_threshold"]
PMTNET_RANK = NEOANTIGEN_CONFIG["pmtnet_rank"]
RNAFOLD_ENERGY_THRESHOLD = NEOANTIGEN_CONFIG["rnafold_energy_threshold"]
OUTPUT_TMP = CONFIG_YAML["TOOL"]["RNAFOLD"]["output_tmp_dir"]


# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)


async def wrap_summary_llm_model_async_stream(
    model: BaseChatModel, 
    system_prompt: str
) -> RunnableSerializable[Dict[str, Any], AsyncIterator[AIMessage]]:
    """包装模型，使其接受 `{"user_input": "..."}` 并返回流式 AI 响应"""
    
    async def stream_response(inputs: Dict[str, Any]) -> AsyncIterator[AIMessage]:
        # 构造消息：系统提示 + 用户输入
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=inputs["user_input"])
        ]
        
        # 流式调用模型
        async for chunk in model.astream(messages):
            yield chunk
    
    return RunnableLambda(stream_response)


def filter_rnafold(input_file_path: str, rnafold_energy_threshold: float) -> str:
    """
    从MinIO下载RNAFold结果，过滤MFE结构，并上传到molly桶
    
    Args:
        input_file_path (str): MinIO路径，格式如 "minio://rnafold-results/54656457_RNAFold_results.xlsx"
        rnafold_energy_threshold (float): 自由能过滤阈值
    
    Returns:
        str: 新文件的MinIO路径（如 "minio://molly/filtered_54656457_RNAFold_results.xlsx"）
    """
    try:
        # 1. 解析MinIO路径
        if not input_file_path.startswith("minio://"):
            raise ValueError("Input path must start with 'minio://'")
        
        path_without_prefix = input_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        
        # 2. 下载文件到临时本地路径
        local_temp_path = f"{OUTPUT_TMP}/{uuid.uuid4().hex}.xlsx"
        minio_client.fget_object(bucket_name, object_name, local_temp_path)
        
        # 3. 读取Excel并过滤MFE结构
        df = pd.read_excel(local_temp_path)
        
        # 提取自由能值（从"MFE结构"列）
        df["MFE_energy"] = df["MFE结构"].str.extract(r'\((-?\d+\.\d+)\)').astype(float)
        filtered_df = df[df["MFE_energy"] <= rnafold_energy_threshold]
        
        # 4. 保存过滤结果到新文件
        filtered_local_path = f"{OUTPUT_TMP}/filtered_{Path(object_name).name}"
        filtered_df.to_excel(filtered_local_path, index=False)
        
        # 5. 上传到molly桶
        random_id = uuid.uuid4().hex
        new_object_name = f"{random_id}_filter_RNAFold_results.xlsx"
        minio_client.fput_object(
            "molly",  # 目标桶名
            new_object_name,
            filtered_local_path
        )
        
        # 6. 清理临时文件
        Path(local_temp_path).unlink(missing_ok=True)
        Path(filtered_local_path).unlink(missing_ok=True)
        
        return f"minio://molly/{new_object_name}"
    
    except S3Error as e:
        raise Exception(f"MinIO操作失败: {e}")
    except Exception as e:
        raise Exception(f"处理失败: {e}")


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
    filter_rnafold_result_file_path=None

    #初始化工具过程流式输出
    writer = get_stream_writer()
    
    # 初始化 GPT-4 模型
    summary_llm = get_model(
        FileDescriptionName.GPT_4O, FileDescriptionName.TEMPERATURE, 
        FileDescriptionName.MAX_TOKENS, FileDescriptionName.BASE_URL, 
        FileDescriptionName.FREQUENCY_PENALTY
    )    

    ######################### 第一步：蛋白切割位点预测 #################################
    writer("# 正在将您的输入的蛋白质文件，进行蛋白切割位点预测，请稍后。\n")
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
                return json.dumps(
                    {
                        "type": "text",
                        "content": "蛋白切割位点阶段未找到符合长度和剪切条件的肽段"
                    }, 
                    ensure_ascii = False
                )
        except S3Error as e:
            return json.dumps(
                {
                    "type": "text",
                    "content": f"蛋白切割位点阶段NetChop_Cleavage工具执行失败: {str(e)}"
                }, 
                ensure_ascii = False
            )    
        
    # 检查是否成功获取文件路径
    if not cleavage_result_file_path:
        return json.dumps(
            {
                "type": "text",
                "content": "蛋白切割位点阶段未生成有效结果文件"
            }, 
            ensure_ascii = False
        )     
    writer("## 蛋白切割位点阶段已完成，已经将您输入的蛋白质切割成一些有效的肽段。\n")  

    ######################### 第二步：pMHC结合亲和力预测 #################################
    writer("# 现在正在将蛋白切割位点预测阶段获取的有效肽段进行pMHC结合亲和力预测，请稍后。\n")  
    mhc_allele_str = ",".join(mhc_allele) 
    netmhcpan_result = await NetMHCpan.arun({"input_file" : cleavage_result_file_path,"mhc_allele" : mhc_allele_str})
    try:
        netmhcpan_result_dict = json.loads(netmhcpan_result)
    except json.JSONDecodeError:
        return json.dumps(
            {
                "type": "link", 
                "url":{"result_file_url": cleavage_result_file_path},
                "content": f"pMHC结合亲和力预测阶段NetMHCpan工具执行失败"
            }, 
            ensure_ascii = False
        )
    
    # 检查NetMHCpan是否成功
    if netmhcpan_result_dict.get("type") != "link":
        # 直接返回NetMHCpan的错误信息
        # return netmhcpan_result
        return json.dumps(
            {
                "type": "link", 
                "url":{"result_file_url": cleavage_result_file_path,  },
                "content": f"pMHC结合亲和力预测阶段未成功运行，{netmhcpan_result_dict['content']}"
            }, 
            ensure_ascii = False
        )
        
    #获取肽段
    netmhcpan_result_file_path = netmhcpan_result_dict["url"]
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
        return json.dumps(
            {
                "type": "link", 
                "url":{"result_file_url": cleavage_result_file_path,},
                "content": f"pMHC结合亲和力预测阶段未成功运行，无法从 MinIO 读取文件: {str(e)}"
            },
            ensure_ascii = False
        )
    # 筛选BindLevel为SB的行
    writer("## pMHC结合亲和力预测结果以获取，结果如下：\n") 
    writer(f"{netmhcpan_result_dict['content']}。\n")
    writer("### 接下来为您分析获取结果\n")

    model_runnable = await wrap_summary_llm_model_async_stream(summary_llm, NETMHCPAN_PROMPT)
    
    # 模拟输入
    inputs = {"user_input": netmhcpan_result_dict["content"]}
    
    # 流式获取输出
    async for chunk in model_runnable.astream(inputs):
        # print(chunk)
        # writer(chunk.content) 
        continue

    writer(f"\n## 接下来为您筛选符合BindLevel为{BIND_LEVEL_ALTERNATIVE}要求的高亲和力的肽段，请稍后。\n") 

    sb_peptides = df[df['BindLevel'].str.strip().isin(BIND_LEVEL_ALTERNATIVE)]

    # 检查是否存在SB肽段
    if sb_peptides.empty:
        return json.dumps(
            {
               "type": "link", 
               "url":{"result_file_url": cleavage_result_file_path,},
               "content": f"pMHC结合亲和力预测阶段结束，NetMHCpan工具未找到高亲和力肽段"
            },
            ensure_ascii = False
        )

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
    except Exception as e:
        raise

    netmhcpan_result_file_path = f"minio://molly/{netmhcpan_result_fasta_filename}"
    writer(f"## 已完成筛选符合要求的高亲和力的肽段，结果如下：\n     {fasta_str}，\n接下来将对这些高亲和力肽段进行细胞内的抗原呈递概率预测，请稍后。\n") 
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

    writer(f"## 已完成细胞内的抗原呈递概率预测，结果如下：\n") 
    writer(f"{bigmhc_el_result_dict['content']}。\n")
    writer("## 以下是对结果进行一定的分析。\n")
    model_runnable = await wrap_summary_llm_model_async_stream(summary_llm, BIGMHC_EL_PROMPT)
    
    # 模拟输入
    inputs = {"user_input": bigmhc_el_result_dict["content"]}
    
    # 流式获取输出
    async for chunk in model_runnable.astream(inputs):
        # print(chunk)
        # writer(chunk.content) 
        continue
    writer(f"\n## 接下来为您筛选为BigMHC_EL >= {BIGMHC_EL_THRESHOLD}的抗原呈递概率的肽段，请稍后。\n") 
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
    writer(f"## 已完成筛选符合要求的抗原呈递概率的肽段，结果如下：\n     {fasta_str}，\n接下来将对这些肽段进行pMHC免疫原性预测，请稍后。\n")     
    ############################## 第三步 pMHC免疫原性预测 ##########################################
    writer("# 现在正在将pMHC结合亲和力预测阶段获取的有效肽段进行pMHC免疫原性预测，请稍后。\n")  
    bigmhc_im_result = await BigMHC_IM.arun({"input_file": bigmhc_el_result_file_path})  

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
    writer("## pMHC免疫原性预测预测结果以获取，结果如下：\n") 
    writer(f"{bigmhc_im_result_dict['content']}。\n")
    writer("### 接下来为您分析获取结果\n")  

    model_runnable = await wrap_summary_llm_model_async_stream(summary_llm, BIGMHC_IM_PROMPT)
    
    # 模拟输入
    inputs = {"user_input": bigmhc_im_result_dict["content"]}
    
    # 流式获取输出
    async for chunk in model_runnable.astream(inputs):
        # print(chunk)
        # writer(chunk.content) 
        continue      

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
    writer(f"\n## 接下来为您筛选符合BigMHC_IM >={BIGMHC_IM_THRESHOLD}要求的高亲和力的肽段，请稍后。\n") 
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
            MOLLY_BUCKET,
            bigmhc_im_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
    except Exception as e:
        raise 
    bigmhc_im_result_file_path = f"minio://molly/{bigmhc_im_result_fasta_filename}"
    writer(f"## 已完成筛选符合要求的高免疫原性的肽段，结果如下：\n     {fasta_str}，\n") 

    if cdr3_sequence == None:
        # result = {
        #     "type": "link",
        #     "url": bigmhc_im_result_file_path,
        #     "content": "提供的下载下载链接是筛选到合适的肽段以及对应的HLA分型"  # 替换为生成的 Markdown 内容
        # }
        # return json.dumps(result, ensure_ascii=False)
        # writer("## 未提供cdr3序列无法进行下一步pMHC-TCR相互作用预测。\n")
        writer("## 未提供cdr3序列无法进行下一步pMHC-TCR相互作用预测。\n")
        writer("## 正在将上面筛选到的高免疫肽段进行mRNA筛选，请稍后。\n") 
        #pMHC免疫原性预测阶段筛选mRNA流程代码逻辑
        cds_result = await concatenate_peptides_with_linker(bigmhc_im_result_file_path)
        if cds_result != None:
            utr_spacer_rnafold_result_url,utr_spacer_rnafold_result_content=await utr_spacer_rnafold_to_mrna(cds_result)
            result_str = str(utr_spacer_rnafold_result_url)
            if result_str.endswith('.xlsx'):
                writer("## mRNA筛选流程结果以获取，结果如下，在肽段信息这一列中：linear代表线性mRNA，circular代码环状mRNA：\n") 
                writer(f"{utr_spacer_rnafold_result_content}。\n")
                writer("### 接下来为您分析获取结果\n")
                model_runnable = await wrap_summary_llm_model_async_stream(summary_llm, RNAFOLD_PROMPT)
                
                # 模拟输入
                inputs = {"user_input": utr_spacer_rnafold_result_content}
                
                # 流式获取输出
                async for chunk in model_runnable.astream(inputs):
                    # print(chunk)
                    # writer(chunk.content) 
                    continue                

                filter_rnafold_result_file_path = filter_rnafold(result_str,RNAFOLD_ENERGY_THRESHOLD)

                writer(f"\n## 接下来为您筛选符合MFE结构 <= {RNAFOLD_ENERGY_THRESHOLD}的mRNA，请稍后在filter_RNAFold_results.xlsx文件中查看。\n")
                return json.dumps(
                    {
                        "type": "link",
                        "url": {
                            "cleavage_result_result_file_url": cleavage_result_file_path,
                            "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                            "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                            "filter_rnafold_file_url": filter_rnafold_result_file_path
                        },
                        "content": (
                        f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                        f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                        f"pMHC免疫原性预测阶段文件已生成，请下载 bigmhc_im.fasta 文件查看。\n"
                        f"mRNA筛选流程文件已生成，请下载filter_RNAFold_results.xlsx文件查看。\n"
                        f"未提供cdr3序列无法进行下一步pMHC-TCR相互作用预测"
                        ),
                    },
                    ensure_ascii=False,
                )                        
            else:
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
                        f"mRNA筛选过程中预测其最小自由能（MFE）二级结构出现问题：{result_str}\n"
                        f"未提供cdr3序列无法进行下一步pMHC-TCR相互作用预测"
                        ),
                    },
                    ensure_ascii=False,
                )   
        else:
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
                    f"生成cds区过程中未能正确执行完成，无法进行下一步mRNA筛选过程。"
                    f"未提供cdr3序列无法进行下一步pMHC-TCR相互作用预测"
                    ),
                },
                ensure_ascii=False,
            )                    

    #第四步 pMHC-TCR相互作用预测         
    else:
        writer("# 正在将筛选出来的高免疫原性肽段，进行pMHC-TCR相互作用预测，请稍后。\n")

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
    writer("## pMHC-TCR相互作用预测结果以获取，结果如下：\n") 
    writer(f"{pmtnet_result_dict['content']}。\n")
    writer("### 接下来为您分析获取结果\n")    

    model_runnable = await wrap_summary_llm_model_async_stream(summary_llm, PMTNET_PROMPT)
    
    # 模拟输入
    inputs = {"user_input": pmtnet_result_dict["content"]}
    
    # 流式获取输出
    async for chunk in model_runnable.astream(inputs):
        # print(chunk)
        # writer(chunk.content) 
        continue

    if cdr3_sequence != "complete":
        # # return pmtnet_result_dict
        # return json.dumps(
        #     {
        #         "type": "link",
        #         "url": {
        #             "cleavage_result_result_file_url": cleavage_result_file_path,
        #             "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
        #             "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
        #             "pmtnet_result_file_url": pmtnet_result_file_path,
        #         },
        #         "content": (
        #             f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
        #             f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
        #             f"pMHC免疫原性预测阶段文件已生成，请下载 bigmhc_im.fasta 文件查看。\n"
        #             f"pMHC-TCR相互作用预测文件已生成,请下载pMTnet_results.csv文件根据需求选择rank值对应的肽段，rank值越大，结合力越强。\n"
        #             f"未提供完整的cdr3序列无法更进一步精准的进行下一步pMHC-TCR相互作用预测\n"
        #         ),
        #     },
        #     ensure_ascii=False,
        # )     
        # 解析MinIO文件路径，提取桶名和文件名
        try:
            
            # 去掉minio://前缀
            path_without_prefix = pmtnet_result_file_path[len("minio://"):]
            
            # 找到第一个斜杠位置，分割桶名和文件名
            first_slash_index = path_without_prefix.find("/")
            
            if first_slash_index == -1:
                raise ValueError("文件路径格式错误：缺少桶名或文件名")
            
            bucket_name = path_without_prefix[:first_slash_index]  # 提取桶名
            object_name = path_without_prefix[first_slash_index + 1:]  # 提取文件名
            
        except Exception as e:
            # 如果解析失败，返回错误信息
            return json.dumps(
                {
                    "type": "link",
                    "url": {
                        "cleavage_result_result_file_url": cleavage_result_file_path,
                        "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                        "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                    },
                    "content": (
                        f"前三步结果文件已生成\n"
                        f"pMHC-TCR相互作用预测阶段失败，解析文件路径失败: {str(e)}"
                    ),
                },
                ensure_ascii=False,
            )

        # 从MinIO读取CSV文件并筛选Rank ≥ PMTNET_RANK的肽段
        try:
            writer(f"\n## 接下来为您筛选符合Rank >={PMTNET_RANK}要求的的肽段，请稍后。\n") 
            # 从MinIO获取文件
            response = minio_client.get_object(bucket_name, object_name)
            csv_data = BytesIO(response.read())
            
            # 读取CSV文件到DataFrame
            df = pd.read_csv(csv_data)
            
            # 筛选Rank值大于等于0.2的行
            high_rank_peptides = df[df['Rank'] >= PMTNET_RANK]
            
            # 检查是否有符合条件的肽段
            if high_rank_peptides.empty:
                # 如果没有符合条件的肽段，返回提示信息
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
                        f"pMHC-TCR相互作用预测文件已生成,请下载pMTnet_results.csv文件查看。\n"
                        f"未找到Rank ≥ {PMTNET_RANK}的高亲和力肽段，无法进行下一步的mRNA筛选流程"
                        ),
                    },
                    ensure_ascii=False,
                )
                
            # 构建FASTA文件内容
            fasta_content = []
            for idx, row in high_rank_peptides.iterrows():
                # 获取肽段序列和HLA分型
                peptide = row['Antigen']
                mhc_allele = row['HLA']
                
                # 创建FASTA条目，格式为：>peptide|MHC_allele
                fasta_content.append(f">{peptide}|{mhc_allele}")  # 标题行
                fasta_content.append(peptide)  # 序列行

            # 合并为完整的FASTA字符串
            fasta_str = "\n".join(fasta_content)

            # 生成唯一的文件名
            uuid_name = str(uuid.uuid4())
            pmtnet_filtered_fasta_filename = f"{uuid_name}_pmtnet_filtered.fasta"

            # 将FASTA文件上传到MinIO的molly桶
            try:
                fasta_bytes = fasta_str.encode('utf-8')  # 编码为字节
                fasta_stream = BytesIO(fasta_bytes)      # 转换为字节流
                minio_client.put_object(
                    MOLLY_BUCKET,  # 桶名
                    pmtnet_filtered_fasta_filename,  # 文件名
                    data=fasta_stream,  # 文件数据
                    length=len(fasta_bytes),  # 文件长度
                    content_type='text/plain'  # 文件类型
                )
            except Exception as e:
                raise 
            
            # 生成文件路径
            pmtnet_filtered_file_path = f"minio://molly/{pmtnet_filtered_fasta_filename}"
            writer(f"## 已完成筛选pMHC-TCR相互作用预测的肽段，结果如下：\n     {fasta_str}，\n接下来将对这些肽段进行mRNA筛选，请稍后。\n") 
            #pMHC-TCR相互作用预测阶段筛选mRNA流程代码逻辑
            cds_result = await concatenate_peptides_with_linker(pmtnet_filtered_file_path)
            if cds_result != None:
                utr_spacer_rnafold_result_url,utr_spacer_rnafold_result_content=await utr_spacer_rnafold_to_mrna(cds_result)
                result_str = str(utr_spacer_rnafold_result_url)
                if result_str.endswith('.xlsx'):
                    writer("## mRNA筛选流程结果以获取，结果如下，在肽段信息这一列中：linear代表线性mRNA，circular代码环状mRNA：\n") 
                    writer(f"{utr_spacer_rnafold_result_content}。\n")
                    writer("### 接下来为您分析获取结果\n")
                    model_runnable = await wrap_summary_llm_model_async_stream(summary_llm, RNAFOLD_PROMPT)
                    
                    # 模拟输入
                    inputs = {"user_input": utr_spacer_rnafold_result_content}
                    
                    # 流式获取输出
                    async for chunk in model_runnable.astream(inputs):
                        # print(chunk)
                        # writer(chunk.content) 
                        continue                

                    filter_rnafold_result_file_path = filter_rnafold(result_str,RNAFOLD_ENERGY_THRESHOLD)

                    writer(f"\n## 接下来为您筛选符合MFE结构 <= {RNAFOLD_ENERGY_THRESHOLD}的mRNA，请稍后在filter_RNAFold_results.xlsx文件中查看。\n")
                    return json.dumps(
                        {
                            "type": "link",
                            "url": {
                                "cleavage_result_result_file_url": cleavage_result_file_path,
                                "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                                "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                                "pmtnet_result_file_url": pmtnet_result_file_path,
                                "filter_rnafold_file_url": filter_rnafold_result_file_path
                            },
                            "content": (
                            f"蛋白切割位点预测阶段文件已生成，请下载 cleavage_result.fasta 文件查看。\n"
                            f"pMHC结合亲和力预测阶段文件已生成，请下载 bigmhc_el.fasta 文件查看。\n"
                            f"pMHC免疫原性预测阶段文件已生成，请下载 bigmhc_im.fasta 文件查看。\n"
                            f"pMHC-TCR相互作用预测文件已生成,请下载pMTnet_results.csv文件查看。\n"
                            f"mRNA筛选流程文件已生成，请下载filter_RNAFold_results.xlsx文件查看。\n"
                            ),
                        },
                        ensure_ascii=False,
                    )                        
                else:
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
                            f"pMHC-TCR相互作用预测文件已生成,请下载pMTnet_results.csv文件查看。\n"
                            f"mRNA筛选过程中预测其最小自由能（MFE）二级结构出现问题：{result_str}\n"
                            ),
                        },
                        ensure_ascii=False,
                    )   
            else:
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
                        f"pMHC-TCR相互作用预测文件已生成,请下载pMTnet_results.csv文件查看。\n"
                        f"生成cds区过程中未能正确执行完成，无法进行下一步mRNA筛选过程。"
                        ),
                    },
                    ensure_ascii=False,
                )                    

            
        except S3Error as e:
            # 如果读取文件失败，返回错误信息
            return json.dumps(
                {
                    "type": "link",
                    "url": {
                        "cleavage_result_result_file_url": cleavage_result_file_path,
                        "bigmhc_el_result_file_url": bigmhc_el_result_file_path,
                        "bigmhc_im_result_file_url": bigmhc_im_result_file_path,
                    },
                    "content": (
                        f"前三步结果文件已生成\n"
                        f"pMHC-TCR相互作用预测阶段失败，无法从MinIO读取文件: {str(e)}"
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
