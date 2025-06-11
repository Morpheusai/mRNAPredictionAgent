import json
import sys
import uuid

from typing import Tuple, List
from minio import Minio
from io import BytesIO
import pandas as pd
from pathlib import Path
from minio.error import S3Error

from src.model.agents.tools.NetMHCPan.netmhcpan import NetMHCpan
from src.model.agents.tools.BigMHC.bigmhc import BigMHC_EL

current_file = Path(__file__).resolve()
project_root = current_file.parents[5]
sys.path.append(str(project_root))
from config import CONFIG_YAML

NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
BIND_LEVEL_ALTERNATIVE = NEOANTIGEN_CONFIG["bind_level_alternative"]  
BIGMHC_EL_THRESHOLD = NEOANTIGEN_CONFIG["bigmhc_el_threshold"]

async def step2_pmhc_binding_affinity(
    cleavage_result_file_path: str, 
    netchop_final_result_str:str,
    mhc_allele: List[str],
    writer,
    mrna_design_process_result: list,
    minio_client: Minio
) -> tuple:
    """
    第二步：pMHC结合亲和力预测
    
    Args:
        cleavage_result_file_path: 切割结果文件路径
        netchop_final_result_str: 切割结果内容的字符串
        mhc_allele: MHC等位基因列表
        writer: 流式输出写入器
        mrna_design_process_result: 过程结果记录列表
    
    Returns:
        tuple: (bigmhc_el_result_file_path, fasta_str) 结果文件路径和FASTA内容
    """
    mhc_allele_str = ",".join(mhc_allele)
    
    # 步骤开始描述
    STEP2_DESC1 = f"""
## 第2部分-pMHC结合亲和力预测
基于NetMHCpan工具对下述内容进行pMHC亲和力预测 
当前输入文件内容: \n
```
{netchop_final_result_str}
```
\n参数设置说明：
- MHC等位基因(mhc_allele): 指定用于预测的MHC分子类型
- 高亲和力阈值(high_threshold_of_bp): (结合亲和力百分位数≤此值判定为强结合)
- 低亲和力阈值(low_threshold_of_bp): (结合亲和力百分位数≤此值判定为弱结合)
- 肽段长度(peptide_length): (预测时考虑的肽段长度范围)

当前使用配置：
- 选用MHC allele: {mhc_allele_str}
- 高亲和力阈值: 0.5%
- 低亲和力阈值: 2%
- 分析肽段长度: 8,9,10,11
"""
    writer(STEP2_DESC1)
    mrna_design_process_result.append(STEP2_DESC1)
    
    # 运行NetMHCpan工具
    netmhcpan_result = await NetMHCpan.arun({
        "input_file": cleavage_result_file_path,
        "mhc_allele": mhc_allele_str
    })
    try:
        netmhcpan_result_dict = json.loads(netmhcpan_result)
    except json.JSONDecodeError:
        raise Exception("pMHC结合亲和力预测阶段NetMHCpan工具执行失败")
    
    if netmhcpan_result_dict.get("type") != "link":
        raise Exception(netmhcpan_result_dict.get("content", "pMHC结合亲和力预测阶段NetMHCpan工具执行失败"))
    
    netmhcpan_result_file_path = netmhcpan_result_dict["url"]
    
    # 读取NetMHCpan结果文件
    try:
        path_without_prefix = netmhcpan_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        response = minio_client.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)
    except S3Error as e:
        raise Exception(f"无法从MinIO读取NetMHCpan结果文件: {str(e)}")
    
    # 筛选高亲和力肽段
    sb_peptides = df[df['BindLevel'].str.strip().isin(BIND_LEVEL_ALTERNATIVE)]
    
    # 步骤中间描述
    INSERT_SPLIT = \
    f"""
    """   
    writer(INSERT_SPLIT)        
    STEP2_DESC2 = f"""
### 第2部分-pMHC结合亲和力预测结束\n
pMHC结合亲和力预测结果已获取，结果如下：\n
{netmhcpan_result_dict['content']}\n
\n接下来筛选符合BindLevel为{BIND_LEVEL_ALTERNATIVE}要求的高亲和力的肽段，请稍后\n
"""
    writer(STEP2_DESC2)
    mrna_design_process_result.append(STEP2_DESC2)
    
    if sb_peptides.empty:
        STEP2_DESC3 = f"""
### 第2部分-pMHC结合亲和力预测结束
未筛选到符合BindLevel为{BIND_LEVEL_ALTERNATIVE}要求的高亲和力的肽段，筛选流程结束。
"""
        writer(STEP2_DESC3)
        mrna_design_process_result.append(STEP2_DESC3)
        raise Exception("pMHC结合亲和力预测阶段结束，NetMHCpan工具未找到高亲和力肽段")
    
    # 构建FASTA内容
    fasta_content = []
    for idx, row in sb_peptides.iterrows():
        identity = row['Identity']
        peptide = row['Peptide']
        fasta_content.append(f">{identity}")
        fasta_content.append(peptide)
    
    netmhcpan_fasta_str = "\n".join(fasta_content)
    
    # 上传FASTA文件到MinIO
    uuid_name = str(uuid.uuid4())
    netmhcpan_result_fasta_filename = f"{uuid_name}_netmhcpan.fasta"
    
    try:
        fasta_bytes = netmhcpan_fasta_str.encode('utf-8')
        fasta_stream = BytesIO(fasta_bytes)
        minio_client.put_object(
            "molly",
            netmhcpan_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
    except Exception as e:
        raise Exception(f"上传FASTA文件失败: {str(e)}")
    
    STEP2_DESC4 = \
f"""
### 第2部分-pMHC结合亲和力预测并筛选结束
已完成筛选符合要求的高亲和力的肽段，结果如下：
```
{netmhcpan_fasta_str}
```
接下来利用BigMHC_EL工具将对这些高亲和力肽段进行细胞内的抗原呈递概率预测

\n参数设置说明：
- MHC等位基因(mhc_allele): 指定用于预测的MHC分子类型

当前使用配置：
- 选用MHC allele: {mhc_allele}
"""   
    writer(STEP2_DESC4)
    mrna_design_process_result.append(STEP2_DESC4)

    # 运行BigMHC_EL工具
    netmhcpan_result_file_path = f"minio://molly/{netmhcpan_result_fasta_filename}"
    bigmhc_el_result = await BigMHC_EL.arun({
        "input_file": netmhcpan_result_file_path,
        "mhc_alleles": mhc_allele
    })
    
    try:
        bigmhc_el_result_dict = json.loads(bigmhc_el_result)
    except json.JSONDecodeError:
        raise Exception("结合亲和力预测阶段BigMHC_el工具执行失败")
    
    if bigmhc_el_result_dict.get("type") != "link":
        raise Exception(bigmhc_el_result_dict.get("content", "pMHC结合亲和力预测阶段BigMHC_el工具执行失败"))
    
    bigmhc_el_result_file_path = bigmhc_el_result_dict["url"]
    
    # 读取BigMHC_EL结果文件
    try:
        path_without_prefix = bigmhc_el_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        response = minio_client.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)
    except S3Error as e:
        raise Exception(f"无法从MinIO读取BigMHC_EL结果文件: {str(e)}")
    
    # 步骤中间描述2
    INSERT_SPLIT = \
    f"""
    """   
    writer(INSERT_SPLIT)    
    STEP2_DESC5 = f"""
### 第2部分-pMHC细胞内抗原呈递概率预测结束\n
已完成细胞内的抗原呈递概率预测，结果如下：\n
{bigmhc_el_result_dict['content']}

接下来为您筛选为BigMHC_EL >= {BIGMHC_EL_THRESHOLD}的抗原呈递概率的肽段
"""
    writer(STEP2_DESC5)
    mrna_design_process_result.append(STEP2_DESC5)
    
    # 筛选高抗原呈递概率肽段
    high_affinity_peptides = df[df['BigMHC_EL'] >= BIGMHC_EL_THRESHOLD]
    
    if high_affinity_peptides.empty:
        STEP2_DESC6 = f"""
### 第2部分-pMHC结合亲和力预测结束
未筛选到符合BigMHC_EL >= {BIGMHC_EL_THRESHOLD}要求的高抗原呈递概率的肽段，筛选流程结束。
"""
        writer(STEP2_DESC6)
        mrna_design_process_result.append(STEP2_DESC6)
        raise Exception(f"未找到高亲和力肽段(BigMHC_EL ≥ {BIGMHC_EL_THRESHOLD})")
    
    # 构建FASTA文件内容
    fasta_content = []
    for idx, row in high_affinity_peptides.iterrows():
        peptide = row['pep']
        mhc_allele = row['mhc']
        
        # 标准化MHC等位基因格式
        if 'HLA-' in mhc_allele and '*' not in mhc_allele.split('HLA-')[1][:2]:
            parts = mhc_allele.split('HLA-')
            if len(parts) > 1:
                allele_part = parts[1]
                if len(allele_part) > 1 and allele_part[1].isdigit():
                    mhc_allele = f"HLA-{allele_part[0]}*{allele_part[1:]}"
        
        fasta_content.append(f">{peptide}|{mhc_allele}")
        fasta_content.append(peptide)
    
    bigmhc_el_fasta_str = "\n".join(fasta_content)
    
    # 上传FASTA文件到MinIO
    uuid_name = str(uuid.uuid4())
    bigmhc_el_result_fasta_filename = f"{uuid_name}_bigmhc_el.fasta"
    
    try:
        fasta_bytes = bigmhc_el_fasta_str.encode('utf-8')
        fasta_stream = BytesIO(fasta_bytes)
        minio_client.put_object(
            "molly",
            bigmhc_el_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
    except Exception as e:
        raise Exception(f"上传FASTA文件失败: {str(e)}")
    
    # 步骤完成描述
    INSERT_SPLIT = \
    f"""
    """   
    writer(INSERT_SPLIT)    
    STEP2_DESC7 = f"""
### 第2部分-pMHC细胞内抗原呈递概率预测结束并完成筛选
已完成细胞内的抗原呈递概率筛选，结果如下：
```fasta
{bigmhc_el_fasta_str}
```
"""
    writer(STEP2_DESC7)
    mrna_design_process_result.append(STEP2_DESC7)
#    model_runnable = await wrap_summary_llm_model_async_stream(summary_llm, NETMHCPAN_PROMPT)
#    # 模拟输入
#    inputs = {"user_input": netmhcpan_result_dict["content"]}
#    # 流式获取输出
#    async for chunk in model_runnable.astream(inputs):
#        # print(chunk)
#        # writer(chunk.content) 
#        continue
    
    return f"minio://molly/{bigmhc_el_result_fasta_filename}", bigmhc_el_fasta_str
