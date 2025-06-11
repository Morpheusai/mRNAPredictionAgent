import json
import aiohttp
import asyncio
import os
import traceback
import tempfile


from langchain_core.tools import tool
import pandas as pd
from typing import Optional,List

from src.utils.minio_utils import upload_file_to_minio,download_from_minio_uri
from src.utils.log import logger
from config import CONFIG_YAML

piste_url = CONFIG_YAML["TOOL"]["PISTE"]["url"]
download_dir = CONFIG_YAML["TOOL"]["PISTE"]["output_tmp_piste_dir"]
minio_bucket = CONFIG_YAML["MINIO"]["piste_bucket"]

def extract_antigen_sequences(input_file) -> List[str]:

    if not (isinstance(input_file, str) and input_file.startswith("minio://")):
        raise ValueError("输入必须是MinIO路径 (格式: minio://bucket/path)")
    local_path = None
    try:
        # 从MinIO下载文件
        local_path = download_from_minio_uri(input_file, download_dir)
        
        sequences = []
        current_seq = ""
        with open(local_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    if current_seq:  # 保存上一个序列
                        sequences.append(current_seq)
                        current_seq = ""
                else:
                    current_seq += line
            
            if current_seq:  # 添加最后一个序列
                sequences.append(current_seq)
        
        if not sequences:
            raise ValueError("FASTA文件中未找到有效肽序列")
            
        return sequences
    
        
    finally:
        # 确保删除临时文件
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                raise(f"警告: 无法删除临时文件 {local_path}: {e}")
    
def normalize_hla_alleles(allele_list):
    normalized = []
    for allele in allele_list:
        # 去除所有空格和可能的*
        allele = allele.replace(" ", "").replace("*", "")
        
        # 处理没有HLA前缀的情况（如A0201或A02:01）
        if not allele.startswith("HLA-"):
            # 检查是否以A/B/C开头，后面跟着数字（可能没有冒号）
            if allele[0] in ["A", "B", "C"]:
                # 处理A0201（无冒号）的情况
                if ":" not in allele:
                    # 确保格式是A0201 -> A02:01（假设前两位是基因，后两位是编号）
                    allele = f"{allele[:1]}{allele[1:3]}:{allele[3:]}"
                # 添加HLA-前缀
                allele = "HLA-" + allele
            else:
                # 其他格式可能需要额外处理
                pass
        
        # 确保冒号后的编号是两位（如HLA-A02:01而不是HLA-A02:1）
        if ":" in allele:
            parts = allele.split(":")
            if len(parts) == 2:
                # 补全冒号后的数字为两位
                parts[1] = parts[1].zfill(2)
                allele = ":".join(parts)
        
        normalized.append(allele)
    
    return normalized



@tool
async def PISTE(
    cdr3_list: List[str],
    input_file: str,  # 现在可以是MinIO路径或本地路径
    mhc_alleles: List[str],
    model_name: Optional[str] = None,
    threshold: Optional[float] = None,
    antigen_type: Optional[str] = None
) -> str:
    """
    PISTE是一个pMHC-TCR相互作用预测的工具
    Args:
        cdr3_list: CDR3序列列表
        input_file: FASTA文件路径（可以是MinIO路径如minio://bucket/file.fasta或本地路径）
        mhc_alleles: MHC等位基因列表（与CDR3一一对应）
        model_name (str, optional): 模型名称，如 "random"、"unipep"、"reftcr"
        threshold (float, optional): binder 阈值（0-1）
        antigen_type (str, optional): 抗原类型，"MT" 或 "WT"

    Returns:
        str: JSON 格式预测结果
    """
    # 验证输入长度是否一致
    if len(cdr3_list) != len(mhc_alleles):
        raise ValueError("cdr3_list和mhc_alleles长度必须一致")
    peptides = extract_antigen_sequences(input_file)
    if len(peptides) != len(cdr3_list):
        raise ValueError(f"FASTA文件中的肽序列数量({len(peptides)})与CDR3序列数量({len(cdr3_list)})不匹配")  #TODO不能是raise，要return，不然会出错
 #兼容各种hla写法   
    mhc_alleles = normalize_hla_alleles(mhc_alleles)
    # 创建临时CSV文件
    temp_csv = None
    try:
        # 创建DataFrame
        df = pd.DataFrame({
            "CDR3": cdr3_list,
            "MT_pep": peptides,
            "HLA_type": mhc_alleles
        })
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as temp_file:
            temp_csv = temp_file.name
            df.to_csv(temp_file, index=False)

        minio_path = upload_file_to_minio(
            local_file_path=temp_csv,
            bucket_name=minio_bucket,
        )
        
        payload = {"input_file_dir_minio": minio_path}
        if model_name:
            payload["model_name"] = model_name
        if threshold is not None:
            payload["threshold"] = threshold
        if antigen_type:
            payload["antigen_type"] = antigen_type

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(piste_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()

    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()
        return json.dumps({
            "type": "text",
            "content": f"调用远程 PISTE 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)
    finally:
        # 清理临时CSV文件
        if temp_csv and os.path.exists(temp_csv):
            try:
                os.remove(temp_csv)
            except Exception as e:
                logger.warning(f"删除临时CSV文件失败: {e}")

#  测试入口（本地运行）
if __name__ == "__main__":
    test_input_path = "minio://molly/39e012fc-a8ed-4ee4-8a3b-092664d72862_piste_example.csv"

    async def test():
        result = await PISTE.ainvoke({
            "input_file_dir": test_input_path,
            "model_name": "unipep",
            "threshold": 0.5,
            "antigen_type": "MT"
        })
        print("异步调用结果：")
        print(result)

    asyncio.run(test())
