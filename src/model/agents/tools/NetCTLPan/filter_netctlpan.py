import re


def filter_netctlpan_output(output_lines: list) -> str:
    """
    过滤 netctlpan 的输出，提取关键信息并生成 Markdown 表格，按 %Rank 排序。

    参数:
        output_lines (list): netctlpan 的输出文本列表，每行为一个字符串。

    返回:
        str: 包含标题、Markdown 表格及总结信息的字符串。
    """
    filtered_data = []

    # 提取标题（假设第一行是标题行，若无则为空）
    header_line = f"**{output_lines[0].strip()}**\n" if output_lines and not output_lines[0].startswith(
        "#") else ""

    for line in output_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()

        try:
            sequence_name = parts[1]    # Sequence Name
            mhc = parts[2]             # MHC 等位基因
            peptide = parts[3]         # 肽序列
            mhc_score = float(parts[4])  # MHC 分数
            tap = float(parts[5])      # TAP 分数
            cle = float(parts[6])      # Cle 分数
            comb = float(parts[7])     # Comb 分数
            rank = float(parts[8])     # %Rank

            data_entry = {
                "Sequence_Name": sequence_name,
                "Peptide": peptide,
                "MHC": mhc,
                "MHC_Score": mhc_score,
                "TAP": tap,
                "Cle": cle,
                "Comb": comb,
                "Rank": rank
            }

            filtered_data.append(data_entry)
        except (IndexError, ValueError):
            continue

    # 如果没有有效数据，返回警告
    if not filtered_data:
        return "\n**警告**: 未找到任何符合条件的肽段，请检查输入数据或参数设置。"

    # 按 %Rank 升序排序（%Rank 越小越好）
    sorted_data = sorted(filtered_data, key=lambda x: x['Rank'])

    # 限制返回行数
    display_data = sorted_data[:7] if len(sorted_data) > 7 else sorted_data
    extra_message = "\n⚠️ 结果超过 7 行，仅显示前 7 行，全部内容请下载表格查看。" if len(
        sorted_data) > 7 else ""

    # 构建 Markdown 表格
    markdown_lines = [
        header_line,
        "| Sequence Name | Peptide Sequence | MHC(HLA Allele) | MHC Score | TAP | Cle | Comb | %Rank |",
        "|---------------|------------------|-----------------|-----------|-----|-----|------|-------|"
    ]

    for item in display_data:
        markdown_lines.append(
            f"| {item['Sequence_Name']} | {item['Peptide']} | {item['MHC']} | {item['MHC_Score']:.3f} | {item['TAP']:.3f} | {item['Cle']:.3f} | {item['Comb']:.3f} | {item['Rank']:.2f} |"
        )

    markdown_lines.append(extra_message)
    markdown_lines.append(
        f"\n**当前结果**: 已完成肽段的筛选，我可以对 {display_data[0]['Peptide']}（%Rank 最优肽段）进行进一步分析，请问是否继续？"
    )

    return "\n".join(markdown_lines)
