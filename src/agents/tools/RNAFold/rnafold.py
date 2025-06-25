import aiohttp
import json
import traceback

from langchain_core.tools import tool

from config import CONFIG_YAML

rnafold_url = CONFIG_YAML["TOOL"]["RNAFOLD"]["url"]

@tool
async def RNAFold(
    input_file: str,
) -> str:
    """                                    
    RNAFold是预测其最小自由能（MFE）二级结构，输出括号表示法和自由能值。
    Args:                                  
        input_file (str): 输入的肽段序例fasta文件路径           
    Returns:                               
        str: 返回输出括号表示法和自由能值字符串。                                                                                                                          
    """
    
    payload = {
        "input_file": input_file,
    }

    timeout = aiohttp.ClientTimeout(total=300)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(rnafold_url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        print("发生异常类型：", type(e).__name__)
        print("异常信息：", str(e))
        traceback.print_exc()

        return json.dumps({
            "type": "text",
            "content": f"调用 RNAPlot 服务失败: {type(e).__name__} - {str(e)}"
        }, ensure_ascii=False)