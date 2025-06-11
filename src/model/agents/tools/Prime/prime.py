import aiohttp
import asyncio
import json
import traceback


from langchain_core.tools import tool
from typing import List,  Optional

from config import CONFIG_YAML

prime_url = CONFIG_YAML["TOOL"]["PRIME"]["url"]
@tool
async def Prime(
    input_file: str,
    mhc_alleles: Optional[List[str]] = None
) -> str:
    """
    Prime 是一款用于预测 I 类免疫原性表位的工具，结合 MHC-I 亲和力与 TCR 识别倾向。

    参数:
    - input_file: MinIO 中的肽段 fasta 文件路径（如 minio://bucket/file.fasta）
    - mhc_alleles: 列表类型，默认为A0101"）

    返回:
    - JSON 字符串，包含预测结果或错误信息
    """

    if mhc_alleles:  # 检查列表是否非空
        mhc_alleles_str = ",".join(allele.strip() for allele in mhc_alleles)
    else:
        mhc_alleles_str = "A0101"  # 如果列表是 None 或空，返回A0101
    payload = {
        "input_file": input_file,
        "mhc_allele": mhc_alleles_str
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(prime_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f" Prime工具调用失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)

if __name__ == "__main__":
    async def test():
        result = await Prime.ainvoke({
            "input_file": "minio://molly/8d886b1b-718a-488a-93d5-a2ee50dcf16d_prime_test.txt",
            "mhc_allele": "A0101,B0801"
        })
        print("Prime 调用结果：")
        print(result)

    asyncio.run(test())
