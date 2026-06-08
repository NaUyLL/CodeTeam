"""Agent 后端抽象 — Room 层不关心具体实现

CodeTeam 只定义接口，不做实现。
底层 Agent 可以是一切：LLM Agent、CLI 工具、甚至真人。
"""

from __future__ import annotations
from abc import ABC, abstractmethod


class AgentBackend(ABC):
    """底层 Agent 抽象 — 只需要实现 act 和序列化"""

    @abstractmethod
    def act(self, instruction: str) -> str:
        """执行一次指令，返回最终回复文本"""

    def decide(self, context: str) -> bool:
        """轻量决策：根据上下文判断是否要发言。默认 True（举手）。"""
        return True

    @abstractmethod
    def get_system_prompt(self) -> str:
        """返回系统提示（用于构建 AgentMember 的 _system_prompt）"""

    @abstractmethod
    def to_dict(self) -> dict:
        """序列化状态，至少包含 type 字段"""

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict, **kwargs) -> AgentBackend:
        """从字典恢复"""
