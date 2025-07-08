import json
import requests
from config import CONFIG_YAML
from src.utils.log import logger

def send_ai_message_to_server(conversation_id, ai_message):
    """
    发送AI消息到服务器，写入messages表
    :param conversation_id: 会话ID
    :param ai_message: AI消息内容
    :return: None
    """
    message_url = CONFIG_YAML["TOOL"]["COMMON"]["handle_ai_message_url"]
    payload = {
        "conversation_id": conversation_id,
        "ai_message": ai_message
    }
    headers = {
        'Content-Type': 'application/json'
    }
    logger.info(f"请求 handle_ai_message: url={message_url}, payload={payload}")
    try:
        response = requests.post(
            message_url,
            headers=headers,
            data=json.dumps(payload)
        )
        logger.info(f"handle_ai_message 返回状态码: {response.status_code}, 返回内容: {response.text}")
    except Exception as e:
        logger.error(f"调用 handle_ai_message 接口失败: {e}") 