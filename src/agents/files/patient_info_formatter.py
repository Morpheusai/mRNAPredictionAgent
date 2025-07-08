from datetime import date
from enum import Enum

from pydantic import BaseModel, Field
from typing import Optional

from src.core import get_model, settings
from .prompt.patient_info_prompts import PATIENT_INFO_SYSTEM_PROMPT

from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

class Gender(str, Enum):
    MALE = '男'
    FEMALE = '女'
    OTHER = '其他'

class BloodType(str, Enum):
    A = 'A'
    B = 'B'
    AB = 'AB'
    O = 'O'
    UNKNOWN = 'unknown'

class StatusType(str, Enum):
    new = 'new'
    pending = 'pending'
    completed = 'completed'

class PatientInfoFormatter(BaseModel):
    """用于格式化病人信息的结构化输出模型"""
    # 基本信息
    medical_record_number: Optional[str]= Field(description="病历号", max_length=50)
    name: Optional[str] = Field(description="患者姓名", max_length=64)
    gender: Gender = Field(description="性别：男/女/其他")
    birth_date: Optional[date] = Field(default=None, description="出生日期")
    phone: Optional[str] = Field(description="联系电话", max_length=20)
    email: Optional[str] = Field(description="电子邮箱", max_length=100)
    hospital: str = Field(description="就诊医院", max_length=64)
    
    # 医疗信息
    blood_type: BloodType = Field(description="血型：A/B/AB/O/未知")
    tumor_type: str = Field(description="肿瘤类型/癌种", max_length=32)
    HLA_type: Optional[str] = Field(description="HLA分型结果", max_length=64)
    CDR_type: Optional[str] = Field(description="CDR(互补决定区)数据", max_length=64)
    treatment_state: str = Field(description="治疗阶段状态", max_length=64)
    additional_info: Optional[str] = Field(description="附加信息/备注")
    clinical_medication: Optional[str] = Field(description="临床用药记录")
    clinical_diagnosis: Optional[str] = Field(description="临床诊断信息")
    status: StatusType = Field(description="状态/new/pending/completed，默认是new") 


# ----------------- 结构化输出系统提示词与Prompt模板 -----------------
# 创建系统提示模板
patient_info_system_prompt = SystemMessagePromptTemplate.from_template(PATIENT_INFO_SYSTEM_PROMPT)
# 创建用户输入模板
patient_info_human_template = "收到的病人信息内容:'''{patient_info}'''."
patient_info_human_prompt = HumanMessagePromptTemplate.from_template(patient_info_human_template)
# 组合提示模板
patient_info_chat_prompt = ChatPromptTemplate.from_messages([patient_info_system_prompt, patient_info_human_prompt])
# 初始化 GPT-4 模型
patient_info_agent = get_model(settings.DEFAULT_MODEL)

# ----------------------------------------------------------------------

# 创建带结构化输出的模型
patient_info_structured = patient_info_agent.with_structured_output(PatientInfoFormatter) 

# 创建处理链
PatientInfoDescriptionAgent = patient_info_chat_prompt | patient_info_structured