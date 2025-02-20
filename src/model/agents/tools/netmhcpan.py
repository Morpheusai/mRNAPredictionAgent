import asyncio

from langchain.tools import tool
from pathlib import Path

async def run_netmhcpan(
    input_path: str, 
    #    allele: str = "HLA-A02:01",
    netmhcpan_dir: str = "/mnt/softwares/netMHCpan-4.1/Linux_x86_64"
    ) -> None:
    """
    异步运行netMHCpan并保存处理后的结果
    :param input_path: 输入文件路径
    :param output_path: 输出文件路径
    :param allele: MHC等位基因类型
    :param netmhcpan_dir: netMHCpan安装目录
    """
    output_path = "/mnt/ljs_tmp/result/netmhcpan_results.txt"  # 输出文件路径
    # 确保输出目录存在
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # 构建命令参数
    bin_path = f"{netmhcpan_dir}/bin/netMHCpan"
    cmd = [
        bin_path,
        input_path,
        # "-a", allele,
        # "-l", "8,9,10,11"  # 根据示例输出添加默认参数
    ]

    # 启动异步进程
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=f"{netmhcpan_dir}/bin"  # 设置工作目录
    )

    # 读取输出
    stdout, stderr = await proc.communicate()
    
    # 处理输出
    output = stdout.decode()
    start_marker = "# NetMHCpan version 4.1b"
    filtered = []
    capture = False

    for line in output.splitlines():
        if start_marker in line:
            capture = True
        if capture:
            filtered.append(line)
 
    # 写入处理后的结果
    with open(output_path, "w") as f:
        f.write("\n".join(filtered))
    
    # 检查执行结果
    if proc.returncode != 0:
        error_msg = stderr.decode()
        raise RuntimeError(f"netMHCpan执行失败，错误信息：{error_msg}")

    #return "\n".join(filtered)
    return output_path

@tool
def NetMHCpan(input_filename: str):
    """
    Predict neoantigens using the NetMHCpan model. Input File path string, returns File path string.
    Args:
        input_path: The path to the input file.
    """
    try:
        return asyncio.run(run_netmhcpan(input_filename))
    except RuntimeError as e:
        return f"调用NetMHCpan工具失败: {e}"
    except Exception as e:
        return f"调用NetMHCpan工具失败: {e}"
