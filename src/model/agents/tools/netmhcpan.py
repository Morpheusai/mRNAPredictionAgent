import asyncio
import sys
import os
from langchain.tools import tool
from pathlib import Path
import uuid

current_file = Path(__file__).resolve()
project_root = current_file.parents[4]  # 向上回溯 4 层目录：src/model/agents/tools → src/model/agents → src/model → src → 项目根目录
                                        
# 将项目根目录添加到 sys.path
sys.path.append(str(project_root))
from config import CONFIG_YAML

# llm 
NETMHCPAN_DIR = CONFIG_YAML["TOOL"]["netmhcpan_dir"]
INPUT_TMP_DIR = CONFIG_YAML["TOOL"]["input_tmp_dir"]
DOWNLOADER_PREFIX = CONFIG_YAML["TOOL"]["ouput_download_url_prefix"]
OUTPUT_TMP_DIR = CONFIG_YAML["TOOL"]["output_tmp_dir"]

async def run_netmhcpan(
    input_filecontent: str, 
    #    allele: str = "HLA-A02:01",
    netmhcpan_dir: str = NETMHCPAN_DIR
    ) -> None:
    """
    异步运行netMHCpan并保存处理后的结果
    :param input_filecontent: 输入文件内容
    :param allele: MHC等位基因类型
    :param netmhcpan_dir: netMHCpan安装目录
    """

    # 生成随机ID和文件路径
    random_id = uuid.uuid4().hex
    base_path = Path(__file__).resolve().parents[3]  # 根据文件位置调整层级
    input_dir = base_path / INPUT_TMP_DIR
    output_dir =Path(OUTPUT_TMP_DIR)
    
    # 创建目录
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    

    # 写入输入文件
    input_path = input_dir / f"{random_id}.fsa"
    with open(input_path, "w") as f:
        f.write(input_filecontent)

    # 构建输出路径
    output_filename = f"netmhcpan_result_{random_id}.txt"
    output_path = output_dir / f"{output_filename}"

    # 构建命令
    cmd = [
        f"{netmhcpan_dir}/bin/netMHCpan",
        str(input_path)
    ]

    # 启动异步进程
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=f"{netmhcpan_dir}/bin"
    )

    # 处理输出
    stdout, stderr = await proc.communicate()
    output = stdout.decode()
    
    # 过滤结果
    filtered = []
    capture = False
    for line in output.splitlines():
        if "# NetMHCpan version" in line:
            capture = True
        if capture:
            filtered.append(line)

    # 写入结果文件
    with open(output_path, "w") as f:
        f.write("\n".join(filtered))

    # 错误处理
    if proc.returncode != 0:
        error_msg = stderr.decode()
        input_path.unlink()  # 删除临时输入文件
        raise RuntimeError(f"netMHCpan执行失败: {error_msg}")

    result = {
        'type': 'link',
        'content': DOWNLOADER_PREFIX + str(output_filename)
    }
    return result

@tool
def NetMHCpan(input_filecontent: str):
    """
    Use the NetMHCpan model to predict new antigens based on the input file content.
    Args:
        input_filecontent: Input the content of the file
    """
    try:
        return asyncio.run(run_netmhcpan(input_filecontent))
    except RuntimeError as e:
        return f"调用NetMHCpan工具失败: {e}"
    except Exception as e:
        return f"调用NetMHCpan工具失败: {e}"