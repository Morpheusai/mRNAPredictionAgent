import json
import aiohttp
import traceback


from langchain_core.tools import tool
from typing import Optional

from config import CONFIG_YAML

netchop_url = CONFIG_YAML["TOOL"]["NETCHOP"]["url"]
@tool
async def NetChop(
    input_filename: str,
    cleavage_site_threshold: Optional[float] = 0.5,
    model: Optional[int] = 0,
    format: Optional[int] = 0,
    strict: Optional[int] = 0
) -> str:
    """
    自动调用远程 NetChop 工具进行蛋白质切割位点预测。

    参数说明：
    - input_filename: MinIO 路径，例如 minio://bucket/path.fasta
    - cleavage_site_threshold: 切割阈值（默认 0.5，范围 0~1）
    - model: 预测模型版本 (默认 0): 0=Cterm3.0, 1=20S-3.0
    - format: 输出格式 (默认 0): 0=长格式, 1=短格式
    - strict: 关闭严格模式 (默认 0): 0=开启严格模式

    返回：
    - str：NetChop 服务返回的 JSON 结果
    """
    
    payload = {
        "input_filename": input_filename,
        "cleavage_site_threshold": cleavage_site_threshold,
        "model": model,
        "format": format,
        "strict": strict
    }

    timeout = aiohttp.ClientTimeout(total=CONFIG_YAML["TOOL"]["COMMON"]["timeout_seconds"])
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(netchop_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f"调用远程 NetChop 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)


if __name__ == "__main__":
    test_input = "minio://molly/ab58067f-162f-49af-9d42-a61c30d227df_test_netchop.fsa"

    import asyncio
    async def test():
        result = await NetChop.ainvoke({
            "input_filename": test_input,
            "cleavage_site_threshold": 0.6,
            "model": 0,
            "format": 0,
            "strict": 0
        })
        print("异步调用结果：")
        print(result)

    asyncio.run(test())

