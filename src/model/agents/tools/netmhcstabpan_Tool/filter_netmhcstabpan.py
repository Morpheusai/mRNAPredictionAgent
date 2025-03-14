import re
def filter_netmhcstabpan_output(output_lines: list) -> str:
    """
    过滤 netMHCstabpan 的输出，提取关键信息并生成 Markdown 表格

    参数:
        output_lines (list): netMHCstabpan 的输出文本列表，每行为一个字符串

    返回:
        str: 包含标题、Markdown 表格及总结信息的字符串
    """
    filtered_data = []

    # 提取标题（若输出行数足够，从倒数第三行获取标题，否则为空）
    header_line = f"**{output_lines[-3].strip()}**\n" if len(output_lines) >= 3 else ""

    # 解析每一行数据
    for line in output_lines:
        line = line.strip()
        # 忽略空行或注释行
        if not line or line.startswith("#"):
            continue
        if "WB" in line or "SB" in line:
            parts = line.split()
                
            try:
                # 根据各字段的位置提取信息
                mhc = parts[1]              # MHC 等位基因
                peptide = parts[2]          # 肽序列
                pred = float(parts[4])      # 预测值
                thalf = float(parts[5])     # 半衰期
                rank_stab = float(parts[6]) # %Rank_Stab
                bind_level = re.search(r"(WB|SB)", line).group(0)
            except (IndexError, ValueError):
                continue

            filtered_data.append({
                "Peptide": peptide,
                "MHC": mhc,
                "Pred": pred,
                "T_half": thalf,
                "Rank_Stab": rank_stab,
                "Bind_Level": bind_level
            })

    # 根据预测值降序排列（最优的排在最前面）
    sorted_data = sorted(filtered_data, key=lambda x: x['Pred'], reverse=True)

    # 构建 Markdown 表格头部
    markdown_lines = [
        header_line,
        "| Peptide Sequence | MHC(HLA Allele) | Pred Score | T_half (h) | %Rank_Stab | Bind Level |",
        "|------------------|-----------------|------------|------------|------------|------------|"
    ]

    # 将数据填充到 Markdown 表格中，格式化浮点数保留两位小数
    for item in sorted_data:
        markdown_lines.append(
            f"| {item['Peptide']} | {item['MHC']} | {item['Pred']:.3f} | {item['T_half']:.2f} | {item['Rank_Stab']:.2f} | {item['Bind_Level']} |"
        )

    # 根据是否有符合条件的数据添加总结信息
    if sorted_data:
        markdown_lines.append(
            f"\n**当前结果**: 已完成肽段的筛选，我可以对 {sorted_data[0]['Peptide']}（最优肽段）进行结构的预测，请问是否继续？"
        )
    else:
        markdown_lines.append(
            "\n**警告**: 未找到任何符合条件的肽段，请检查输入数据或参数设置。"
        )

    return "\n".join(markdown_lines)
