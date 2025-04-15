def filter_netmhcpan_output() -> str:
    """
    动态解析工具输出并生成 Markdown 表格（兼容列名和数量变化）
    
    Args:
        output_lines (list): 输出内容（按行分割的列表）
        
    Returns:
        str: 生成的 Markdown 表格字符串
    """
    import re

    # ========== 第一部分：动态提取表头和数据 ==========
    # 找到数据部分（示例中数据在第二个 "####################" 后）
    output_file="/mnt/softwares/PRIME/test/out2.txt"
    data_content = []
    header = []
    filtered_data = []

    # 读取文本文件内容
    with open(output_file, 'r') as f:
        content = f.read()
    
    # 找到第二个 "####################" 之后的内容
    sections = content.split('####################')
    if len(sections) < 3:
        return "**错误**: 未能正确生成结果"
    
    data_section = sections[2].strip()  # 第二个分割后的部分是实际数据
    
    # 按行分割数据
    data_content = data_section.split('\n')        # 读取文本文件内容



    # 提取表头和数据行
    if len(data_content) >= 1:
        # 表头是第一非空行，用制表符或连续空格分割
        header = re.split(r'\t|\s{2,}', data_content[0])
        for row in data_content[1:]:
            cols = re.split(r'\t|\s{2,}', row.strip())
            if len(cols) == len(header):
                filtered_data.append(dict(zip(header, cols)))

    # ========== 第二部分：动态生成表格 ==========
    # 生成Markdown表头
    if not header:
        return "**错误**: 未检测到有效表头"
    markdown_table = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |"
    ]


    # 填充数据行
    for row in filtered_data:
        markdown_table.append(
            "| " + " | ".join(str(row.get(col, "")) for col in header) + " |"
        )

    # ========== 第三部分：生成结果提示 ==========
    final_output = "\n".join(markdown_table)
    
    if filtered_data:
        pass
    else:
        final_output += (
            "\n\n**警告**: 未找到有效数据，请检查：\n"
            "1. 输入文件格式是否符合要求\n"
            "2. 列名是否包含关键字段（如 Score）"
        )
    
    return final_output
filter_netmhcpan_output()