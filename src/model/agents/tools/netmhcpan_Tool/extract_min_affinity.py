import json

def extract_min_affinity_peptide(func_result):
    """
    从 func_result 中提取 Affinity (nM) 最小的肽序列。

    参数:
        func_result (str): 包含表格数据的 JSON 字符串。

    返回:
        tuple: 包含最小亲和力 (float) 和对应的肽序列 (str)。
              如果未找到有效数据，返回 (None, None)。
    """
    try:
        # 解析 JSON 字符串
        data = json.loads(func_result)
        # 提取 content 字段
        content = data["content"]
        # 按行分割表格内容
        rows = content.split("\n")

        # 初始化最小亲和力和对应的肽序列
        min_affinity = float("inf")
        min_peptide_sequence = None

        # 遍历每一行
        for row in rows:
            # 忽略表头和空行
            if not row.startswith("|") or "Peptide Sequence" in row or "<td colspan" in row:
                continue
            # 按竖线分割单元格
            cells = [cell.strip() for cell in row.split("|")[1:-1]]
            
            # 提取肽序列和亲和力
            try:
                peptide_sequence = cells[0]
                affinity = float(cells[3])

                # 更新最小亲和力和对应的肽序列
                if affinity < min_affinity:
                    min_affinity = affinity
                    min_peptide_sequence = peptide_sequence
            except (IndexError, ValueError):
                # 如果单元格格式错误，跳过该行
                continue

        # 返回结果
        return min_peptide_sequence

    except (json.JSONDecodeError, KeyError) as e:
        # 如果 JSON 解析失败或缺少 content 字段，返回 None
        print(f"解析 func_result 失败: {e}")
        return None

# # 示例调用
# func_result =r'''
# {"type": "link", "url": "minio://netmhcpan-results/netmhcpan_result_6e97609d3bcb44ccbb7a6067503fe15c.txt", "content": "| Peptide Sequence | HLA Allele | Bind Level | Affinity (nM) |\n|------------------|------------|------------|---------------|\n| AVTEQGHEL | HLA-A*02:01 | WB | 4409.60 |\n| VLQLLDKYL | HLA-A*02:01 | WB | 567.53 |\n| YLIPNATQP | HLA-A*02:01 | WB | 4545.87 |\n| MQPTHPIRL | HLA-A*02:01 | WB | 4507.86 |\n| AFDEAIAEL | HLA-A*02:01 | WB | 1016.96 |\n| QLLRDNLTL | HLA-A*02:01 | SB | 125.08 |\n| <td colspan=\"4\">Protein 143B_BOVIN_P293. Allele HLA-A*02:01. Number of high binders 1. Number of weak binders 5. Number of peptides 237</td> |"}
# '''

# min_peptide, min_affinity = extract_min_affinity_peptide(func_result)
# if min_peptide is not None:
#     print(f"最小亲和力: {min_affinity} nM")
#     print(f"对应的肽序列: {min_peptide}")
# else:
#     print("未找到有效数据。")