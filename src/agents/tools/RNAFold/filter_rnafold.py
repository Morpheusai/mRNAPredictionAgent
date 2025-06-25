import pandas as pd
from src.utils.log import logger

def escape_markdown_special_chars(text: str) -> str:
    # 定义需要转义的特殊字符及其转义形式
    special_chars = {
        '|': '\\|',
        '\\': '\\\\',
        '*': '\\*',
        '_': '\\_',
        '#': '\\#',
        '+': '\\+',
        '-': '\\-',
        '=': '\\=',
        '>': '\\>',
        '<': '\\<',
        '(': '\\(',
        ')': '\\)',
        '!': '\\!',
        '[': '\\[',
        ']': '\\]',
        '{': '\\{',
        '}': '\\}',
        '"': '\\"',
        "'": "\\'",
        '`': '\\`',
        '&': '\\&',
        '%': '\\%',
        '$': '\\$',
        '^': '\\^',
        '~': '\\~',
    }
    # 替换特殊字符
    for char, escaped_char in special_chars.items():
        text = text.replace(char, escaped_char)
    return text

def filter_rnafold_excel(excel_path: str) -> str:
    try:
        # 读取Excel文件
        df = pd.read_excel(excel_path)
        
        # 处理特殊字符和换行符
        df = df.map(lambda x: escape_markdown_special_chars(str(x)).replace('\n', ' '))

        # 生成Markdown表格（对齐表头）
        markdown_table = df.to_markdown(index=False, tablefmt="github")
        
        # 构建完整的Markdown内容
        result = f"""{markdown_table}

---

**说明**：  
• 上表显示肽段的最小自由能(MFE)二级结构预测结果  
• 括号表示法解析：  
  - `(` / `)`：配对的碱基对  
  - `.`：未配对碱基  
• 最后一列为自由能值（单位：kcal/mol）  
"""
        
        return result
        
    except Exception as e:
        logger.error(f"Excel转Markdown失败: {str(e)}")
        return """```
        无法生成结果表格，请检查文件格式是否符合要求
```"""

# 示例调用
# excel_path = "path_to_your_excel_file.xlsx"
# markdown_table = filter_rnafold_excel(excel_path)
# print(markdown_table)
