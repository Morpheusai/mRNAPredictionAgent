from utils import logger
from config import g_config
from code_knowledge_base.code_knowledge_base import CodeKnowledgeBase
from code_knowledge_base.openmmlab_config import Component


code_knowledge_base = CodeKnowledgeBase(kb_config=g_config["knowledge_base"], llm_config=g_config["llm"]["code_parser"])
code_knowledge_base.delete_knowledge_base()
#code_knowledge_base.scan_openmmlab_instances()
code_knowledge_base.scan_openmmlab_docs()

instance_list = code_knowledge_base.retrieve_docs(query_content="代码执行过程中出现了错误，具体是由于配置文件中缺少 'work_dir' 参数导致的 KeyError", project_name=None)
logger.info(f"doc 0: {instance_list[0]}")
assert len(instance_list) > 0

#instance_list = code_knowledge_base.retrieve_instances(query_content="多级特征融合算法", project_name=None)
#logger.info(f"instance 0: {instance_list[0]}")
#assert len(instance_list) > 0

#instance_list = code_knowledge_base.retrieve_instances(query_content="RTMDet", project_name=None)
#logger.info(f"instance 0: {instance_list[0]}")
#assert len(instance_list) > 0

#instance_list = code_knowledge_base.retrieve_instances(query_content="Mask R-CNN", project_name=None)
#logger.info(f"instance 0: {instance_list[0]}")
#assert len(instance_list) > 0
