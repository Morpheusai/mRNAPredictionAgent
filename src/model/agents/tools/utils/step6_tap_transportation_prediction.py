import json
import uuid

from typing import  List
from minio import Minio
from io import BytesIO
import pandas as pd
from minio.error import S3Error

from src.model.agents.tools.NetCTLPan.netctlpan import NetCTLpan

from config import CONFIG_YAML

NEOANTIGEN_CONFIG = CONFIG_YAML["TOOL"]["NEOANTIGEN_SELECTION"]
NETCTLPAN_THRESHOLD = NEOANTIGEN_CONFIG["netctlpan_threshold"]

async def step6_tap_transportation_prediction(
    cleavage_result_file_path: str, 
    netchop_final_result_str:str,
    mhc_allele: List[str],
    writer,
    mrna_design_process_result: list,
    minio_client: Minio,
    neoantigen_message,
    cleavage_m
) -> tuple:
    """
    第二步：TAP转运预测阶段
    
    Args:
        cleavage_result_file_path: 切割结果文件路径
        netchop_final_result_str: 切割结果内容的字符串
        mhc_allele: MHC等位基因列表
        writer: 流式输出写入器
        mrna_design_process_result: 过程结果记录列表
    
    Returns:
        tuple: (netctlpan_result_file_path, netctlpan_fasta_str) 结果文件路径和FASTA内容
    """
    mhc_allele_str = ",".join(mhc_allele)
    mhc_allele_str = mhc_allele[0]
    
    # 步骤开始描述
#     STEP2_DESC1 = f"""
# ## 第2部分-TAP转运预测阶段
# 基于NetCTLpan工具对下述内容进行TAP转运效率预测
# 当前输入文件内容: \n
# ```
# {netchop_final_result_str}
# ```
# """
#     writer(STEP2_DESC1)
#     mrna_design_process_result.append(STEP2_DESC1)
    STEP2_DESC1 = f"""
## 🚚 步骤 2：TAP转运效率预测
目标：排除难以通过抗原加工通路的低效率肽段
"""
    writer(STEP2_DESC1)
    mrna_design_process_result.append(STEP2_DESC1)
    
    # 运行NetCTLpan工具
    netctlpan_result = await NetCTLpan.arun({
        "input_file": cleavage_result_file_path,
        "mhc_allele": mhc_allele_str,
        "peptide_length": "9"
    })
    
    try:
        netctlpan_result_dict = json.loads(netctlpan_result)
    except json.JSONDecodeError:
        raise Exception("TAP转运预测阶段NetCTLpan工具执行失败")
    
    if netctlpan_result_dict.get("type") != "link":
        raise Exception(netctlpan_result_dict.get("content", "TAP转运预测阶段NetCTLpan工具执行失败"))
    
    netctlpan_result_file_path = netctlpan_result_dict["url"]
    
    # 读取NetCTLpan结果文件
    try:
        path_without_prefix = netctlpan_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        response = minio_client.get_object(bucket_name, object_name)
        excel_data = BytesIO(response.read())
        df = pd.read_excel(excel_data)
    except S3Error as e:
        raise Exception(f"无法从MinIO读取NetCTLpan结果文件: {str(e)}")
    
    # 步骤中间描述2
    INSERT_SPLIT = \
    f"""
    """   
    # writer(INSERT_SPLIT)    
    STEP2_DESC5 = f"""
### 第2部分-TAP转运预测阶段结束\n
已完成细胞内的转运效率预测，结果如下：\n
{netctlpan_result_dict['content']}

接下来为您筛选为TAP >= {NETCTLPAN_THRESHOLD}的转运效率的肽段
"""
    # writer(STEP2_DESC5)
    mrna_design_process_result.append(STEP2_DESC5)
    
    # 筛选高转运效率肽段
    high_affinity_peptides = df[df['TAP'] >= NETCTLPAN_THRESHOLD]
    
    if high_affinity_peptides.empty:
        # print("11111111111111111")
        STEP2_DESC6 = f"""
未筛选到符合TAP >= {NETCTLPAN_THRESHOLD}要求的高转运效率概率的肽段，筛选流程结束。
"""
        writer(STEP2_DESC6)
        mrna_design_process_result.append(STEP2_DESC6)
        neoantigen_message[2]=f"0/{cleavage_m}"
        neoantigen_message[3]=netctlpan_result_file_path
        raise Exception(f"未找到高亲和力肽段(TAP ≥ {NETCTLPAN_THRESHOLD})")
    
    # 构建FASTA文件内容
    fasta_content = []
    count=0
    for idx, row in high_affinity_peptides.iterrows():
        peptide = row['Peptide']
        mhc_allele = row['Allele']
        
        fasta_content.append(f">{peptide}|{mhc_allele}")
        fasta_content.append(peptide)
        count +=1
    
    netctlpan_fasta_str = "\n".join(fasta_content)
    
    # 上传FASTA文件到MinIO  
    uuid_name = str(uuid.uuid4())
    netctlpan_result_fasta_filename = f"{uuid_name}_netctlpan.fasta"
    
    try:
        fasta_bytes = netctlpan_fasta_str.encode('utf-8')
        fasta_stream = BytesIO(fasta_bytes)
        minio_client.put_object(
            "molly",
            netctlpan_result_fasta_filename,
            data=fasta_stream,
            length=len(fasta_bytes),
            content_type='text/plain'
        )
    except Exception as e:
        neoantigen_message[2]=f"0/{cleavage_m}"
        neoantigen_message[3]=f"上传FASTA文件失败: {str(e)}"
        raise Exception(f"上传FASTA文件失败: {str(e)}")
    
    # 步骤完成描述
    INSERT_SPLIT = \
    f"""
    """   
    # writer(INSERT_SPLIT)    
    STEP2_DESC7 = f"""
### 第2部分-TAP转运预测阶段结束并完成筛选
已完成细胞内的转运预测阶概率筛选，结果如下：
```fasta
{netctlpan_fasta_str}
```
"""
    # writer(STEP2_DESC7)
    mrna_design_process_result.append(STEP2_DESC7)
#    model_runnable = await wrap_summary_llm_model_async_stream(summary_llm, NETMHCPAN_PROMPT)
#    # 模拟输入
#    inputs = {"user_input": netmhcpan_result_dict["content"]}
#    # 流式获取输出
#    async for chunk in model_runnable.astream(inputs):
#        # print(chunk)
#        # writer(chunk.content) 
#        continue
    STEP2_DESC7 = f"""
✅ 已完成转运评估，剔除部分效率较低肽段，保留**{count}个有效候选肽段**
"""    
    writer(STEP2_DESC7)
    return f"minio://molly/{netctlpan_result_fasta_filename}", netctlpan_fasta_str,count,netctlpan_result_file_path
