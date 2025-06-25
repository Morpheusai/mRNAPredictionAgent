import sys

from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

from src.core import get_model
from src.schema.models import FileDescriptionName

from ...prompt.patient_case_mrna_prompts import RAG_SUMMARY_PROMPT  # Changed to use RAG_SUMMARY_PROMPT

# 构建提示模板 - Updated to use RAG_SUMMARY_PROMPT
system_prompt = SystemMessagePromptTemplate.from_template(RAG_SUMMARY_PROMPT)
human_prompt = HumanMessagePromptTemplate.from_template("原始查询：'''{query}'''")
chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

# ================= 模型配置 =================
vaccine_design_agent = get_model(  # Renamed to better reflect purpose
    FileDescriptionName.GPT_4O, 
    0.0, 
    FileDescriptionName.MAX_TOKENS, 
    FileDescriptionName.BASE_URL, 
    FileDescriptionName.FREQUENCY_PENALTY
)

# ================= 处理链 =================
vaccine_design_chain = chat_prompt | vaccine_design_agent  # Renamed chain

# ================= 业务逻辑 =================
def query_llm(query: str, rag_response: str, files: str) -> str:
    """
    个性化mRNA疫苗设计主函数
    参数:
        query: 原始查询
        rag_response: 检索到的专业内容
        files: 病人信息文件内容
    返回:
        疫苗设计方案和建议
    """
    try:
        # 执行模型调用
        response = vaccine_design_chain.invoke({
            "query": query,
            "rag_response": rag_response,
            "files": files
        })
        
        # 解析响应内容
        if not response.content:
            raise ValueError("Empty response from LLM")
            
        return response.content.strip()
        
    except Exception as e:
        # 降级方案：返回错误信息
        print(f"Error in vaccine design: {str(e)}", file=sys.stderr)
        return f"疫苗设计方案生成失败: {str(e)}。请检查输入数据并重试。"
    
if __name__ == "__main__":
    # Updated test case to match new function signature
    test_query = "请根据我的突变位点设计个性化mRNA疫苗"
    test_rag = "相关文献表明... (示例专业内容)"
    test_files = "病人ID: 123\n突变肽段: XYZ123\n..."
    print(query_llm(test_query, test_rag, test_files))