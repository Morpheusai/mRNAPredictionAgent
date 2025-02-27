from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
import sys
from pathlib import Path  
current_file = Path(__file__).resolve()
project_root = current_file.parents[3]  # 向上回溯 4 层目录：src/model/agents/tools → src/model/agents → src/model → src → 项目根目录
# 将项目根目录添加到 sys.path
sys.path.append(str(project_root))
from config import CONFIG_YAML
model_name = CONFIG_YAML["LLM"]["model_name"]
temperature= CONFIG_YAML["LLM"]["temperature"]
minio_system_prompt = CONFIG_YAML["PROMPT"]["minio_system_prompt"]
# 创建系统提示模板

system_prompt = SystemMessagePromptTemplate.from_template(minio_system_prompt)

# 创建用户输入模板
human_template = "要分析的文件名:'''{file_name}''',需要分析文件的内容:'''{file_content}'''."
human_prompt = HumanMessagePromptTemplate.from_template(human_template)

# 组合提示模板
chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

# 初始化 GPT-4 模型
chat = ChatOpenAI(model_name=model_name, temperature=temperature)
# 创建处理链
chain = chat_prompt | chat 