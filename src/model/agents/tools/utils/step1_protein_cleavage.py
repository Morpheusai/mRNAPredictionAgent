import json
from typing import Tuple, List
from minio import Minio
from io import BytesIO
from src.model.agents.tools.NetChop.netchop import NetChop
from src.model.agents.tools.CleavagePeptide.cleavage_peptide import NetChop_Cleavage
import pandas as pd
from minio.error import S3Error

async def step1_protein_cleavage(input_file: str, writer, mrna_design_process_result: list, minio_client: Minio) -> tuple:
    """
    第一步：蛋白切割位点预测
    
    Args:
        input_file: 输入文件路径
        writer: 流式输出写入器
        mrna_design_process_result: 过程结果记录列表
    
    Returns:
        tuple: (cleavage_result_file_path, fasta_str) 切割结果文件路径和FASTA内容
    """
    cleavage_site_threshold = 0.5
    
    # 步骤描述
    STEP1_DESC1 = f"""
## 第1部分-蛋白切割位点预测\n
### 第1部分-NetChop工具开始\n
对输入的肽段序列进行蛋白切割位点预测
参数设置说明：
- 蛋白质切割位点的置信度阈值(cleavage_site_threshold): 留预测分值高于该阈值的可信切割位点

当前使用配置：
- 选用cleavage_site_threshold: {cleavage_site_threshold}
"""
    writer(STEP1_DESC1)
    mrna_design_process_result.append(STEP1_DESC1)
    
    # 运行NetChop工具
    netchop_result = await NetChop.arun({
        "input_file": input_file,
        "cleavage_site_threshold": cleavage_site_threshold
    })
    
    try:
        netchop_result_dict = json.loads(netchop_result)
    except json.JSONDecodeError:
        raise Exception("蛋白切割位点阶段NetChop工具执行失败")
    
    if netchop_result_dict.get("type") != "link":
        raise Exception(netchop_result_dict.get("content", "蛋白切割位点阶段NetChop工具执行失败"))
    
    netchop_result_file_path = netchop_result_dict["url"]
    
    # 对netchop结果获取肽段fasta文件
    netchop_cleavage_result = await NetChop_Cleavage.arun({
        "input_file": netchop_result_file_path
    })
    
    try:
        cleavage_result_dict = json.loads(netchop_cleavage_result)
    except json.JSONDecodeError:
        raise Exception("蛋白切割位点阶段NetChop_Cleavage工具执行失败")
    
    if cleavage_result_dict.get("type") != "link":
        raise Exception("蛋白切割位点阶段未生成有效结果文件")
    
    cleavage_result_file_path = cleavage_result_dict["url"]
    
    # 验证文件内容
    try:
        path_without_prefix = cleavage_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        response = minio_client.get_object(bucket_name, object_name)
        bytes_io = BytesIO(response.read())
        netchop_final_result_str = bytes_io.getvalue().decode('utf-8')
        
        if len(netchop_final_result_str) == 0:
            raise Exception("蛋白切割位点阶段未找到符合长度和剪切条件的肽段")
    except S3Error as e:
        raise Exception(f"蛋白切割位点阶段NetChop_Cleavage工具执行失败: {str(e)}")
    
    # 步骤完成描述
    INSERT_SPLIT = \
    f"""
    """   
    writer(INSERT_SPLIT)    
    STEP1_DESC2 = """
### 第1部分-NetChop工具完成\n
已经将您输入的肽段序列切割成一些有效的肽段。\n
"""
    writer(STEP1_DESC2)
    mrna_design_process_result.append(STEP1_DESC2)
#model_runnable = await wrap_summary_llm_model_async_stream(
#        summary_llm, 
#        NETCHOP_PROMPT.format(cleavage_site_threshold = cleavage_site_threshold)
#    )
    
    # 模拟输入
#    inputs = {
#        "user_input": f"当前NetChop工具得到的结果内容: {netchop_final_result_str}"
#    }
    
    # 流式获取输出
#    async for chunk in model_runnable.astream(inputs):
#        #print(chunk)
#        #writer(chunk.content) 
#        continue
    

    return cleavage_result_file_path, netchop_final_result_str
