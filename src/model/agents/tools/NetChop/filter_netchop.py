def filter_netchop_output(output_lines: list) -> str:
    """
    过滤 netchop 的输出，提取关键信息并生成 Markdown 表格
    
    Args:
        output_lines (list): netchop 的原始输出内容（按行分割的列表）
        
    Returns:
        str: 生成的 Markdown 表格字符串
    """
    import re

    # 初始化变量
    filtered_data = []
    markdown_content = []

    # ========== 第一部分：处理输出行 ==========
    for line in output_lines:
        line = line.strip()
        
        # 跳过空行和非数据行
        if not line:
            continue

        # 捕获统计信息行（新增对行数的检查）
        if "Number of cleavage" in line and len(output_lines) >= 3:
            markdown_content.append(f"**{output_lines[-3]}**\n")  # 保持原有逻辑，但建议检查索引有效性

        # 处理有效数据行
        if "gi|" in line and len(line.split()) >= 5:
            parts = line.split()
            try:
                # 提取关键字段
                AA = parts[1]  
                C = parts[2]  
                score = float(parts[3])  
                
                filtered_data.append({
                    "AA": AA,
                    "C": C,
                    "score": score,
                })
            except (IndexError, ValueError, AttributeError) as e:
                # 记录错误但不中断流程
                #logo
                continue

    # ========== 第二部分：生成表格 ==========
    # 添加表头
    table_header = [
        "| AA |  C  |  score  |",
        "|----|-----|---------|"
    ]                                  
    
    # 添加排序后的数据行
    sorted_data = sorted(filtered_data, key=lambda x: x['score'], reverse=True)
    for item in sorted_data:
        table_header.append(
            f"| {item['AA']} | {item['C']} | {item['score']} |"
        )

    # ========== 第三部分：生成最终输出 ==========
    # 合并所有内容
    final_output = markdown_content + table_header

    # 添加结果提示（修复 IndexError 的核心修改）
    if filtered_data:
        pass
        # final_output.append(
        #     f"\n**当前结果**: 已完成肽段的筛选，我可以对 {sorted_data[0]['Peptide']}（最优肽段）进行结构的预测，请问是否继续？"
        # )
    else:
        final_output.append(
            "\n**警告**: 未找到任何符合条件，请检查：\n"
            "1. 输入文件是否符合格式要求\n"
            "2. 筛选阈值是否设置合理\n"
        )

    return "\n".join(final_output)