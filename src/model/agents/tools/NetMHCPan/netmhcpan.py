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

netmhcpan_url = CONFIG_YAML["TOOL"]["NETMHCPAN"]["url"]

@tool
async def NetMHCpan(
    input_file: str,
    mhc_allele: str = "HLA-A02:01",
    high_threshold_of_bp: float = 0.5,
    low_threshold_of_bp: float = 2.0,
    peptide_length: str = "8,9,10,11"
) -> str:
    """
    NetMHCpan 用于预测肽段序列与指定 MHC 分子的结合能力。

    参数:
    - input_file: MinIO 路径，例如 minio://bucket/path.fasta
    - mhc_allele: MHC 等位基因
    - high_threshold_of_bp: 高亲和力阈值
    - low_threshold_of_bp: 低亲和力阈值
    - peptide_length: 肽段长度，逗号分隔

    返回:
    - str: JSON 格式的预测结果
    """
    
    payload = {
        "input_file": input_file,
        "mhc_allele": mhc_allele,
        "high_threshold_of_bp": high_threshold_of_bp,
        "low_threshold_of_bp": low_threshold_of_bp,
        "peptide_length": peptide_length
    }

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(netmhcpan_url, json=payload) as response:
                response.raise_for_status()
                return await response.text()
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
        result = await NetMHCpan.ainvoke({
            "input_file": test_input,
            "mhc_allele": "HLA-A02:01,HLA-A24:02,HLA-A26:01",
            "high_threshold_of_bp": 0.5,
            "low_threshold_of_bp": 2.0,
            "peptide_length": "8,9,10,11"
        })
        print("NetMHCpan 异步调用结果：")
        print(result)

    asyncio.run(test())

