import aiohttp
import asyncio
import json
import random
import time


from langchain_core.tools import tool
from typing import Optional

from config import CONFIG_YAML
from src.utils.log import logger


netchop_url = CONFIG_YAML["TOOL"]["NETCHOP"]["url"]
PORT_START = CONFIG_YAML["TOOL"]["COMMON"]["port_start"]
PORT_END = CONFIG_YAML["TOOL"]["COMMON"]["port_end"]
RETRY_TIMES = CONFIG_YAML["TOOL"]["COMMON"]["retry_times"]
TIME_TIMEOUT = CONFIG_YAML["TOOL"]["COMMON"]["timeout_seconds"]


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
        "strict": strict,
        "num_workers":20,        
    }

    
    # total  整个操作的最大秒数，包括建立连接、发送请求和读取响应。
    # connect  如果超出池连接限制，则建立新连接或等待池中的空闲连接的最大秒数。
    # sock_connect  为新连接连接到对等点的最大秒数，不是从池中给出的。
    # sock_read  从对等点读取新数据部分之间允许的最大秒数。
    client_timeout = aiohttp.ClientTimeout(
        total = TIME_TIMEOUT,
        sock_read = TIME_TIMEOUT
    )
    for retry in range(RETRY_TIMES):
        port = random.randint(PORT_START, PORT_END)
        local_addr = ('0.0.0.0', port)
        connector = aiohttp.TCPConnector(
            local_addr = local_addr,
            keepalive_timeout = TIME_TIMEOUT
        )
        try:
            async with aiohttp.ClientSession(connector=connector,timeout=client_timeout) as session:
                async with session.post(netchop_url, timeout=client_timeout, json=payload) as response:
                    response.raise_for_status()
                    return await response.json()
        except Exception as e:
            logger.warning(f"第{retry+1}次调用NetChop服务失败，失败原因：{e}")
            time.sleep(3.0)

    logger.error(f"调用NetChop服务失败，请检查网络和工具服务")
    return json.dumps(
        {
            "type": "text",
            "content": f"调用 NetChop 服务失败: {type(e).__name__} - {str(e)}"
        }, 
        ensure_ascii=False
    )




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

