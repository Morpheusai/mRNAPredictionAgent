from functools import cache
from langchain_openai import ChatOpenAI
from typing import TypeAlias

from src.model.schema.models import (
    AllModelEnum,
    OpenAIModelName,
    FileDescriptionName,
)

_MODEL_TABLE = {
    OpenAIModelName.GPT_4O_MINI: "gpt-4o-mini",
    OpenAIModelName.GPT_4O: "gpt-4o",
    OpenAIModelName.TEMPERATURE: 0.1,
    OpenAIModelName.MAX_TOKENS: None,
    OpenAIModelName.BASE_URL: "https://api.openai.com/v1",
    OpenAIModelName.FREQUENCY_PENALTY: 0.0,

    FileDescriptionName.GPT_4O: "gpt-4o",
    FileDescriptionName.TEMPERATURE: 0.1,
    FileDescriptionName.MAX_TOKENS: None,
    FileDescriptionName.BASE_URL: "https://api.openai.com/v1",
    FileDescriptionName.FREQUENCY_PENALTY: 0.0,
}

ModelT: TypeAlias = (
    ChatOpenAI 
)


@cache
def get_model(model_name: AllModelEnum, 
              model_temperature: AllModelEnum, 
              model_max_tokens: AllModelEnum,
              model_base_url: AllModelEnum, 
              model_frequency_penalty: AllModelEnum,/) -> ModelT:
    # NOTE: models with streaming=True will send tokens as they are generated
    # if the /stream endpoint is called with stream_tokens=True (the default)
    api_model_name = _MODEL_TABLE.get(model_name)
    api_model_temperature = _MODEL_TABLE.get(model_temperature)
    max_completion_tokens = _MODEL_TABLE.get(model_max_tokens)
    api_model_base_url = _MODEL_TABLE.get(model_base_url)
    api_model_frequency_penalty = _MODEL_TABLE.get(model_frequency_penalty)
    if not api_model_name:
        raise ValueError(f"Unsupported model: {model_name}")

    if model_name in OpenAIModelName or model_name in FileDescriptionName:
        return ChatOpenAI(
            model=api_model_name,
            temperature=api_model_temperature,
            max_completion_tokens=max_completion_tokens,
            base_url=api_model_base_url,
            frequency_penalty=api_model_frequency_penalty,
            streaming=True
        )
