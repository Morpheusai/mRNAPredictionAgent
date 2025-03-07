def filter_netmhcpan_output(output_lines: list) -> str:
    """
    过滤 netMHCpan 的输出，提取关键信息并生成 Markdown 表格
    
    Args:
        output_lines (list): netMHCpan 的原始输出内容（按行分割的列表）
        
    Returns:
        str: 生成的 Markdown 表格字符串
    """
    import re

    # 初始化变量
    filtered_data = []

    # 遍历每一行输出
    for line in output_lines:
        line = line.strip()
        

        # 确保是有效数据行（列数 >= 14）并且行包含"WB"或"SB"
        if ("WB" in line or "SB" in line):
            # 处理数据行（关键修改部分）
            parts = line.split()
            try:
                # 提取 HLA, Peptide, BindLevel 和 Affinity
                hla = parts[1]  # HLA 在第二个位置
                peptide = parts[2]   # 处理长肽段
                bind_level = "WB" if "WB" in line else "SB" if "SB" in line else "N/A"  # 判断 BindLevel 是 WB 还是 SB
                affinity = float(parts[-3]) # 亲和力是最后一个值
                
                # 将数据添加到 filtered_data
                filtered_data.append({
                    "Peptide": peptide,
                    "HLA": hla,
                    "BindLevel": bind_level,
                    "Affinity": affinity
                })
            except IndexError:
                continue
    # 生成Markdown表格
    markdown_content = [
        "| Peptide Sequence | HLA Allele | Bind Level | Affinity (nM) |",
        "|------------------|------------|------------|---------------|"
    ]


    # 添加统计信息
    markdown_content.insert(0, f"**{output_lines[-3]}**\n")
    
    # 按照 Affinity 的值从大到小排序
    filtered_data.sort(key=lambda x: x['Affinity'], reverse=True)
    
    for item in filtered_data:
        markdown_content.append(
            f"| {item['Peptide']} | {item['HLA']} | {item['BindLevel']} | {item['Affinity']} |"
        )

    markdown_content.append(f"\n**当前结果**: 已完成亲和力强的肽段的筛选，我可以对{filtered_data[0]['Peptide']}进行结构的预测，请问是否继续？")

    return "\n".join(markdown_content)

