"""CodeTeam — 多 Agent 协作路由层

CodeTeam 不做单个 Agent 的实现。
它只负责：Room（多人对话编排）、AgentMember（成员调度）、AgentBackend（底层接口）。

底层 Agent 可以是任何东西——CoreAgent、OpenCode、甚至一个人。
CodeTeam 的路由层不在乎，它只负责「把消息发出去，把回复收回来」。
"""

__version__ = "0.1.0"

from .room import Room, AgentMember, RoomMessage
from .core.backend import AgentBackend
