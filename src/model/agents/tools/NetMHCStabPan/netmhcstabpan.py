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

netmhcstabpan_url = CONFIG_YAML["TOOL"]["NETMHCSTABPAN"]["url"]

@tool
async def NetMHCstabpan(input_file: str,
                  mhc_allele: str = "HLA-A02:01",
                  high_threshold_of_bp: float = 0.5,
                  low_threshold_of_bp: float = 2.0,
                  peptide_length: str = "8,9,10,11",) -> str:
    """                                    
    NetMHCstabpan用于预测肽段与MHC结合后复合物的稳定性，可用于优化疫苗设计和免疫治疗。
    Args:
        input_file (str): 输入的肽段序列fasta文件路径 
        mhc_allele (str): MHC比对的等位基因
        peptide_length (str): 预测时所使用的肽段长度            
        high_threshold_of_bp (float): 肽段和MHC分子高结合能力的阈值
        low_threshold_of_bp (float): 肽段和MHC分子弱结合能力的阈值
    Returns:
        str: 返回高稳定性的肽段序列信息                                                                                                                           
    """
    
    payload = {
        "input_file": input_file,
        "mhc_allele": mhc_allele,
        "high_threshold_of_bp": high_threshold_of_bp,
        "low_threshold_of_bp": low_threshold_of_bp,
        "peptide_length": peptide_length
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(netmhcstabpan_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f"调用 NetMHCpan 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)
if __name__ == "__main__":
    # test_input = "minio://molly/8e2d5554-cd03-4088-98f4-1766952b4171_B0702.fsa"
    test_input = "minio://netchop-cleavage-results/c8a29857-345d-49cc-bce5-71a5a9fe4864_cleavage_result.fasta"
    async def test():
        result = await NetMHCstabpan.ainvoke({
"input_file":"minio://molly/0bdd5ce9-2705-4335-9b9c-d88a6c7c7831_ab58067f-162f-49af-9d42-a61c30d227df_test_netchop.fsa"
        })
        print("NetMHCstabpan 异步调用结果：")
        print(result)

    asyncio.run(test())

