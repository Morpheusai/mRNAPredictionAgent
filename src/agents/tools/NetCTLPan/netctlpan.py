import aiohttp
import asyncio
import json
import traceback

from langchain_core.tools import tool
from typing import Optional

from config import CONFIG_YAML

netctlpan_url = CONFIG_YAML["TOOL"]["NETCTLPAN"]["url"]

@tool
async def NetCTLpan(
    input_filename: str,
    mhc_allele: str = "HLA-A02:01",
    peptide_length: str = "9",
    weight_of_tap: float = 0.025,
    weight_of_clevage: float = 0.225,
    epi_threshold: float = 1.0,
    output_threshold: float = -99.9,
    sort_by: int = -1,
    mode: int = 0
) -> str:
    """
    使用NetCTLpan工具预测肽段序列与指定MHC分子的结合亲和力，用于筛选潜在的免疫原性肽段。

    参数说明:
    - input_filename: 输入文件路径，例如 minio://bucket/path.fasta
    - mhc_allele: MHC等位基因，默认"HLA-A02:01"，多个用逗号分隔
    - peptide_length: 肽段长度，字符串格式如"9,10"，默认-1（表示8-11），范围8-11
    - weight_of_tap: TAP转运效率权重，默认0.025，权重越低影响越小
    - weight_of_clevage: 切割效率权重，默认0.225，影响大于TAP权重
    - epi_threshold: 表位阈值，默认1.0，高于此值可能为潜在表位
    - output_threshold: 输出阈值，默认-99.9，高于此值的结果才会显示
    - sort_by: 排序方式(-1:不排序, 0:综合分, 1:MHC, 2:切割, 3:TAP)

    返回:
    - str: JSON 格式的预测结果
    """
    
    # 如果 peptide_length 是 -1，转换为默认的 "8,9,10,11"
    
    payload = {
        "input_filename": input_filename,  # 注意：保持 input_file 因为远程服务接口可能还在用这个名字
        "mhc_allele": mhc_allele,
        "weight_of_clevage": weight_of_clevage,
        "weight_of_tap": weight_of_tap,
        "peptide_length": peptide_length,
        "epi_threshold": epi_threshold,
        "output_threshold": output_threshold,
        "sort_by": sort_by,
        "num_workers":20,
        "mode": 1,
        "hla_mode":1, #等于1表示只取传入的第一个hla分型做检测
        "peptide_duplication_mode":1 #为一表示肽段去重
    }

    timeout = aiohttp.ClientTimeout(total=CONFIG_YAML["TOOL"]["COMMON"]["timeout_seconds"])
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(netctlpan_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f"调用 NetCTLpan 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)

if __name__ == "__main__":
    async def test():
        result = await NetCTLpan.ainvoke({
            "input_filename": "minio://molly/2ad83c64-0440-4d70-80bf-8a0054c0ecac_B0702.fsa",
            "mhc_allele": "HLA-A02:01",
            "peptide_length": -1,
            "weight_of_tap": 0.025,
            "weight_of_clevage": 0.225,
            "epi_threshold": 1.0,
            "output_threshold": -99.9,
            "sort_by": -1
        })
        print("NetCTLpan 异步调用结果：")
        print(result)

    asyncio.run(test())




