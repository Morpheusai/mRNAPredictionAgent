from functools import cache
from typing import TypeAlias


from langchain_openai import ChatOpenAI

from src.model.schema.models import (
    AllModelEnum,

    OpenAIModelName,
)

_MODEL_TABLE = {
    OpenAIModelName.GPT_4O_MINI: "gpt-4o-mini",
    OpenAIModelName.GPT_4O: "gpt-4o",

}

ModelT: TypeAlias = (
    ChatOpenAI 
)


@cache
def get_model(model_name: AllModelEnum, /) -> ModelT:
    # NOTE: models with streaming=True will send tokens as they are generated
    # if the /stream endpoint is called with stream_tokens=True (the default)
    api_model_name = _MODEL_TABLE.get(model_name)
    if not api_model_name:
        raise ValueError(f"Unsupported model: {model_name}")

    if model_name in OpenAIModelName:
        return ChatOpenAI(model=api_model_name, temperature=0.1, streaming=True)
    
