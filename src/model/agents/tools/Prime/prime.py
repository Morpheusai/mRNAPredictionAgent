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

prime_url = CONFIG_YAML["TOOL"]["PRIME"]["url"]
@tool
async def Prime(
    input_file: str,
    mhc_allele: str = "A0101"
) -> str:
    """
    Prime 是一款用于预测 I 类免疫原性表位的工具，结合 MHC-I 亲和力与 TCR 识别倾向。

    参数:
    - input_file: MinIO 中的肽段 fasta 文件路径（如 minio://bucket/file.fasta）
    - mhc_allele: MHC-I 等位基因字符串，用逗号分隔（如 "A0101,B0702"）

    返回:
    - JSON 字符串，包含预测结果或错误信息
    """
    
    payload = {
        "input_file": input_file,
        "mhc_allele": mhc_allele
    }

    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(prime_url, json=payload) as response:
                response.raise_for_status()
                return await response.text()
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
