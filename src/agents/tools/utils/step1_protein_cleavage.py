import json
import requests
import time

from io import BytesIO
from minio.error import S3Error

from src.agents.tools.NetChop.netchop import NetChop
from src.agents.tools.parameters import NetchopParameters
from src.agents.tools.CleavagePeptide.cleavage_peptide import NetChop_Cleavage
from src.utils.minio_utils import MINIO_CLIENT
from config import CONFIG_YAML
from src.utils.tool_input_output_api import send_tool_input_output_api
from src.utils.log import logger

handle_url = CONFIG_YAML["TOOL"]["COMMON"]["handle_tool_input_output_url"]

async def step1_protein_cleavage(
        input_parameters: NetchopParameters, 
        writer, 
        neoantigen_message,
        patient_id,
        predict_id,
    ) -> tuple:
    """
    第一步：蛋白切割位点预测
    
    Args:
        input_parameters: netchop输入参数
        writer: 流式输出写入器
    Returns:
        tuple: (cleavage_result_file_path, fasta_str) 切割结果文件路径和FASTA内容
    """
    # 步骤描
    STEP1_DESC1 = f"""
## 🔍 步骤 1：突变肽段生成与切割
目标：识别可能作为抗原呈递单位的8–11mer短肽段
"""

#     STEP1_DESC1 = f"""
# ## 第1部分-蛋白切割位点预测\n
# ### 第1部分-NetChop工具开始\n
# 对输入的肽段序列进行蛋白切割位点预测
# 参数设置说明：
# - 蛋白质切割位点的置信度阈值(cleavage_site_threshold): 留预测分值高于该阈值的可信切割位点

# 当前使用配置：
# - 选用cleavage_site_threshold: {input_parameters.cleavage_site_threshold}
# """
    writer(STEP1_DESC1)
    
    # 调用前置接口
    try:
        send_tool_input_output_api(
            patient_id, 
            predict_id, 
            0, 
            "NetChop", 
            input_parameters.__dict__ if hasattr(input_parameters, '__dict__') else dict(input_parameters)
        )
    except Exception as e:
        logger.error(f"工具前置接口调用失败: {e}")
    
    # 运行NetChop工具
    logger.info("开始执行NetChop工具...")
    start_time = time.time()
    netchop_result = await NetChop.arun(
        {
            "input_filename": input_parameters.input_filename,
            "cleavage_site_threshold": input_parameters.cleavage_site_threshold,
            "model": input_parameters.model,
            "format": input_parameters.format, 
            "strict": input_parameters.strict
        }
    )
    end_time = time.time()
    execution_time = end_time - start_time
    logger.info(f"NetChop工具执行完成，耗时: {execution_time:.2f}秒")

    try:
        netchop_result_dict = json.loads(netchop_result)
        logger.info("NetChop工具结果解析成功")
    except json.JSONDecodeError:
        logger.error("NetChop工具结果JSON解析失败")
        neoantigen_message[0] = f"0/0"
        neoantigen_message[1] =  "蛋白切割位点阶段NetChop工具执行失败"   
        raise Exception("蛋白切割位点阶段NetChop工具执行失败")
        # 调用后置接口
    try:
        send_tool_input_output_api(
            patient_id, 
            predict_id, 
            1, 
            "NetChop", 
            netchop_result_dict
        )
    except Exception as e:
        logger.error(f"工具后置接口调用失败: {e}")
    
    if netchop_result_dict.get("type") != "link":
        logger.error(f"NetChop工具执行失败: {netchop_result_dict.get('content', '未知错误')}")
        neoantigen_message[0] = f"0/0"
        neoantigen_message[1] =  "蛋白切割位点阶段NetChop工具执行失败"   
        raise Exception(netchop_result_dict.get("content", "蛋白切割位点阶段NetChop工具执行失败"))
    
    netchop_result_file_path = netchop_result_dict["url"]
    logger.info(f"NetChop工具结果文件路径: {netchop_result_file_path}")
    
    # 对netchop结果获取肽段fasta文件
    logger.info("开始执行NetChop_Cleavage工具...")
    start_time = time.time()
    netchop_cleavage_result = await NetChop_Cleavage.arun(
        {
            "input_file": netchop_result_file_path
        }
    )
    end_time = time.time()
    execution_time = end_time - start_time
    logger.info(f"NetChop_Cleavage工具执行完成，耗时: {execution_time:.2f}秒")
    
    try:
        cleavage_result_dict = json.loads(netchop_cleavage_result)
        logger.info("NetChop_Cleavage工具结果解析成功")
    except json.JSONDecodeError:
        logger.error("NetChop_Cleavage工具结果JSON解析失败")
        neoantigen_message[0] = f"0/0"
        neoantigen_message[1] =  "蛋白切割位点阶段NetChop_Cleavage工具执行失败"
        raise Exception("蛋白切割位点阶段NetChop_Cleavage工具执行失败")
    
    if cleavage_result_dict.get("type") != "link":
        logger.error(f"NetChop_Cleavage工具执行失败: {cleavage_result_dict.get('content', '未知错误')}")
        neoantigen_message[0] = f"0/0"
        neoantigen_message[1] =  "蛋白切割位点阶段未生成有效结果文件"
        raise Exception("蛋白切割位点阶段未生成有效结果文件")
    
    cleavage_result_file_path = cleavage_result_dict["url"]
    logger.info(f"NetChop_Cleavage工具结果文件路径: {cleavage_result_file_path}")
    
    # 验证文件内容
    try:
        path_without_prefix = cleavage_result_file_path[len("minio://"):]
        bucket_name, object_name = path_without_prefix.split("/", 1)
        logger.info(f"从MinIO读取文件: bucket={bucket_name}, object={object_name}")
        response = MINIO_CLIENT.get_object(bucket_name, object_name)
        bytes_io = BytesIO(response.read())
        netchop_final_result_str = bytes_io.getvalue().decode('utf-8')
        
        if len(netchop_final_result_str) == 0:
            logger.warning("蛋白切割位点阶段未找到符合长度和剪切条件的肽段")
            neoantigen_message[0] = f"0/0"
            neoantigen_message[1] =  "蛋白切割位点阶段未找到符合长度和剪切条件的肽段,筛选流程结束"
            raise Exception("蛋白切割位点阶段未找到符合长度和剪切条件的肽段")
        # 统计以 '>' 开头的行数
        count = sum(1 for line in netchop_final_result_str.splitlines() if line.startswith('>'))
        logger.info(f"成功解析到 {count} 条候选短肽段")
    except S3Error as e:
        logger.error(f"从MinIO读取文件失败: {str(e)}")
        neoantigen_message[0] = f"0/0"
        neoantigen_message[1] =  f"蛋白切割位点阶段NetChop_Cleavage工具执行失败: {str(e)}"
        raise Exception(f"蛋白切割位点阶段NetChop_Cleavage工具执行失败: {str(e)}")
    
    # 步骤完成描述
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
    STEP1_DESC2 = f"""
✅ 系统已成功识别出**{count}条候选短肽段**，进入后续筛选阶段
"""
    writer(STEP1_DESC2)

    return cleavage_result_file_path, netchop_final_result_str,count
