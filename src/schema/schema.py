from pydantic import BaseModel, Field
from typing import Any, Literal,List, NotRequired,Union
from typing_extensions import TypedDict


class AgentInfo(BaseModel):
    """Info about an available agent."""

    key: str = Field(
        description="Agent key.",
        examples=["research-assistant"],
    )
    description: str = Field(
        description="Description of the agent.",
        examples=["A research assistant for generating research papers."],
    )

class FileInfo(BaseModel):
    file_name: str = Field(description="文件名")
    file_content: str = Field(description="文件内容")
    file_path: str = Field(description="文件地址")
    file_desc: str = Field(description="文件描述")
    file_origin: int  = Field(description="文件来源，0表示用户上传，1表示系统文件")

class FileGroup(BaseModel):
    conversation_id: str = Field(description="会话 ID，UUID 格式，长度 36", max_length=36, min_length=36)
    files: List[FileInfo] = Field(description="文件列表")

class UserInput(BaseModel):
    """Basic user input for the agent."""
    prompt: str = Field(
        description="User input to the agent.",
        examples=["_______________________________DQATSLRILNNGHAFNVEFDDSQDKAVLK"or"What is the weather in Tokyo?"],
    )
    conversation_id: str = Field(
        description="传入会话id，存入数据库",
    )
    file_list: List[FileGroup] = Field(
        description="传入文件列表",
        default=[],
    )
    agent_config: dict[str, Any] = Field(
        description="Additional configuration to pass through to the agent",
        default={},
        examples=[{"spicy_level": 0.8}],
    )
    stream_tokens: bool = Field(
        description="Whether to stream LLM tokens to the client.",
        default=True,
    )

class PredictUserInput(BaseModel):
    """Basic user input for the agent."""
    prompt: str = Field(
        description="User input to the agent.",
        examples=["_______________________________DQATSLRILNNGHAFNVEFDDSQDKAVLK"or"What is the weather in Tokyo?"],
    )

    patient_id: int = Field(description="病人id")

    predict_id: int = Field(description="预测表id")
    
    conversation_id: int = Field(
        description="传入会话id，存入数据库",
    )
    file_path: str = Field(
        description="测序文件minio路径",
        examples=["minio://molly/6e461c0b-876c-4a98-9e7e-a743ec71c7b0_bigmhc_el.fasta"],
    )
    mhc_allele: str = Field(
        description="HLA分型",
        examples=["HLA-A*0201，HLA-B*0702"],
    )
    cdr3: List[str] = Field(
        description="cdr3序列",
        examples=[["CASSIRSSYEQYF", "CASSLGQGAEAFF"]],
        default=[],
    )
    parameters: dict[str, Any] = Field(
        description="预测参数",
        default={},
        examples=[
            {
                "netchop": {
                    "cleavage_site_threshold": 0.5,
                    "model": 0,
                    "format": 0,
                    "strict": 0
                },
                "netctlpan": {
                    "peptide_length": -1 ,
                    "weight_of_tap": 0.025,
                    "weight_of_clevage": 0.225,
                    "epi_threshold": 1.0,
                    "output_threshold": -99.9,
                    "sort_by": -1
                },
                "netmhcpan": { 
                    "peptide_length": -1 ,
                    "high_threshold_of_bp": 0.5,
                    "low_threshold_of_bp": 2.0,
                    "rank_cutoff": -99.9,
                },
                "bigmhc_im": {
                }
            }
        ]
    )
    agent_config: dict[str, Any] = Field(
        description="Additional configuration to pass through to the agent",
        default={},
        examples=[{"spicy_level": 0.8}],
    )
    stream_tokens: bool = Field(
        description="Whether to stream LLM tokens to the client.",
        default=True,
    )

class ToolCall(TypedDict):
    """Represents a request to call a tool."""

    name: str
    """The name of the tool to be called."""
    args: dict[str, Any]
    """The arguments to the tool call."""
    id: str | None
    """An identifier associated with the tool call."""
    type: NotRequired[Literal["tool_call"]]


class ChatMessage(BaseModel):
    """Message in a chat."""

    type: Literal["human", "ai", "tool", "custom"] = Field(
        description="Role of the message.",
        examples=["human", "ai", "tool", "custom"],
    )
    content: Union[str, dict] = Field(  # 支持字符串或字典
        description="Content of the message.",
        examples=["Hello, world!", {"type": "text", "content": "Some text"}],
    )
    tool_calls: list[ToolCall] = Field(
        description="Tool calls in the message.",
        default=[],
    )
    tool_call_id: str | None = Field(
        description="Tool call that this message is responding to.",
        default=None,
        examples=["call_Jja7J89XsjrOLA5r!MEOW!SL"],
    )
    run_id: str | None = Field(
        description="Run ID of the message.",
        default=None,
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    response_metadata: dict[str, Any] = Field(
        description="Response metadata. For example: response headers, logprobs, token counts.",
        default={},
    )
    custom_data: dict[str, Any] = Field(
        description="Custom message data.",
        default={},
    )

    def pretty_repr(self) -> str:
        """Get a pretty representation of the message."""
        base_title = self.type.title() + " Message"
        padded = " " + base_title + " "
        sep_len = (80 - len(padded)) // 2
        sep = "=" * sep_len
        second_sep = sep + "=" if len(padded) % 2 else sep
        title = f"{sep}{padded}{second_sep}"
        return f"{title}\n\n{self.content}"

    def pretty_print(self) -> None:
        print(self.pretty_repr())  # noqa: T201


class Feedback(BaseModel):
    """Feedback for a run, to record to LangSmith."""

    run_id: str = Field(
        description="Run ID to record feedback for.",
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    key: str = Field(
        description="Feedback key.",
        examples=["human-feedback-stars"],
    )
    score: float = Field(
        description="Feedback score.",
        examples=[0.8],
    )
    kwargs: dict[str, Any] = Field(
        description="Additional feedback kwargs, passed to LangSmith.",
        default={},
        examples=[{"comment": "In-line human feedback"}],
    )


class FeedbackResponse(BaseModel):
    status: Literal["success"] = "success"


class ChatHistoryInput(BaseModel):
    """Input for retrieving chat history."""

    thread_id: str = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )


class ChatHistory(BaseModel):
    messages: list[ChatMessage]


# 定义请求体模型
class MinioRequest(BaseModel):
    file_name: str
    file_content: str

# 定义响应体模型
class MinioResponse(BaseModel):
    file_description: str

# 定义病人信息请求体模型
class PatientInfoRequest(BaseModel):
    patient_info: str = Field(description="病人的原始信息文本")

# 定义病人信息响应体模型
class PatientInfoResponse(BaseModel):
    structured_info: dict = Field(description="结构化后的病人信息")