import aiohttp
import asyncio
import json
import traceback

from langchain_core.tools import tool
from typing import Optional

from config import CONFIG_YAML

netmhcpan_url = CONFIG_YAML["TOOL"]["NETMHCPAN"]["url"]

@tool
async def NetMHCpan(
    input_filename: str,
    mhc_allele: str = "HLA-A02:01",
    peptide_length: int = -1,
    high_threshold_of_bp: float = 0.5,
    low_threshold_of_bp: float = 2.0,
    rank_cutoff: float = -99.9
) -> str:
    """
    NetMHCpan 用于预测肽段序列与指定 MHC 分子的结合能力。

    参数说明:
    - input_filename: 输入文件路径，例如 minio://bucket/path.fasta
    - mhc_allele: MHC等位基因，默认"HLA-A02:01"，多个用逗号分隔
    - peptide_length: 肽段长度，默认-1（表示8-11），范围8-11
    - high_threshold_of_bp: 高亲和力阈值，默认0.5，越低筛选越严格
    - low_threshold_of_bp: 低亲和力阈值，默认2.0，越高筛选越宽松
    - rank_cutoff: %Rank截断值，默认-99.9，正数时仅输出小于等于该值的结果

    返回:
    - str: JSON 格式的预测结果
    """
    
    payload = {
        "input_filename": input_filename,  # 注意：保持 input_file 因为远程服务接口可能还在用这个名字
        "mhc_allele": mhc_allele,
        "high_threshold_of_bp": high_threshold_of_bp,
        "low_threshold_of_bp": low_threshold_of_bp,
        "peptide_length": peptide_length,
        "rank_cutoff": rank_cutoff
    }

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(netmhcpan_url, json=payload) as response:
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
    test_input = "minio://netchop-cleavage-results/c8a29857-345d-49cc-bce5-71a5a9fe4864_cleavage_result.fasta"
    async def test():
        result = await NetMHCpan.ainvoke({
            "input_filename": test_input,
            "mhc_allele": "HLA-A02:01,HLA-A24:02,HLA-A26:01",
            "peptide_length": -1,
            "high_threshold_of_bp": 0.5,
            "low_threshold_of_bp": 2.0,
            "rank_cutoff": -99.9
        })
        print("NetMHCpan 异步调用结果：")
        print(result)

    asyncio.run(test())

