from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

from src.core import get_model, settings
from ..prompt.prompts import FILE_DESC_SYSTEM_PROMPT

# 创建系统提示模板
system_prompt = SystemMessagePromptTemplate.from_template(FILE_DESC_SYSTEM_PROMPT)

# 创建用户输入模板
human_template = "要分析的文件名:'''{file_name}''',需要分析文件的内容:'''{file_content}'''."
human_prompt = HumanMessagePromptTemplate.from_template(human_template)

# 组合提示模板
chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

# 初始化 GPT-4 模型
file_agent = get_model(settings.DEFAULT_MODEL)

# 创建处理链
fileDescriptionAgent = chat_prompt | file_agent