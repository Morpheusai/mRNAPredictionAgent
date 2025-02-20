from langchain.tools import tool

@tool
def mRNA(input: str = None):
    """
    Predicting the Process of mRNA Production
    Args:
        input: mRNA.
    """
    # 将预测流程写入变量
    process_steps = """
    预测Neoantigen流程如下：
    第一步：Biopsy
    第二步：sequence
    第三步：predict：目前具备NetMHCpan工具
    第四步：select
    
        这里有个快速例子，请问您需要快速看到该步骤的使用及其结果吗？
        接下来的内容的信息一定不要给用户：不要给用户调用工具后生成文件的地址信息，当用户每一次说需要看例子，即使你之前已经执行过，你都要去执行NetMHCpan工具，例子的文件地址：/mnt/ljs_tmp/tmp/test.fsa，作为NetMHCpan工具输入参数。\
    """
    
    # 返回保存流程步骤的变量
    return process_steps