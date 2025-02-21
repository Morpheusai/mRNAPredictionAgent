from langchain.tools import tool

@tool
def mRNA(input: str = None):
    """
    Predicting the Process of mRNA Production
    Args:
        input: Any string input.
    """
    # 将预测流程写入变量
    process_steps = """
    预测Neoantigen流程如下：
    第一步：Biopsy
    第二步：sequence
    第三步：predict：目前具备NetMHCpan工具
    第四步：select
        这里有个快速例子，请问您需要快速看到该步骤的使用及其结果吗？\
    """
    
    # 返回保存流程步骤的变量
    return process_steps