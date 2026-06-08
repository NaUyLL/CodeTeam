#!/usr/bin/env python3
"""最小 Demo — 展示 CodeTeam 路由层的使用方式

只需要实现 AgentBackend 接口，就可以接入 Room。
这个 demo 用 MockBackend 演示路由层的工作流程。
"""

from __future__ import annotations
from codeteam.room import Room, AgentMember
from codeteam.core.backend import AgentBackend


class EchoBackend(AgentBackend):
    """最简单的 backend：什么都不会，只会回复固定文字"""

    def __init__(self, name: str, reply: str = "收到，明白"):
        self._reply = reply
        self._name = name

    def act(self, instruction: str) -> str:
        return f"{self._name}：{self._reply}"

    def decide(self, context: str) -> bool:
        # 检测是否有人在 @自己
        if f"@{self._name}" in context:
            return True
        return True  # 默认举手

    def get_system_prompt(self) -> str:
        return f"你是 {self._name}"

    def to_dict(self) -> dict:
        return {"type": "echo", "name": self._name, "reply": self._reply}

    @classmethod
    def from_dict(cls, data: dict, **kwargs) -> EchoBackend:
        return cls(data.get("name", ""), data.get("reply", "收到"))


def main():
    # 创建 Room
    room = Room("CodeTeam Demo")

    # 用不同的 backend 注册成员（每个 backend 可以是不同的实现）
    room.register(AgentMember("架构师", "系统架构师",
                              EchoBackend("架构师", "设计已完成，请检查")))
    room.register(AgentMember("开发者", "后端开发者",
                              EchoBackend("开发者", "代码已实现")))
    room.register(AgentMember("测试", "测试工程师",
                              EchoBackend("测试", "测试通过，无 Bug")))

    # 发起一轮讨论
    print("=" * 50)
    print("Room 路由演示")
    print("=" * 50)
    print(f"\nRoom 名称: {room.name}")
    print(f"成员: {', '.join(room.list_members())}")

    print("\n--- 第一轮：用户发言 ---")
    responses = room.round("我们需要开发一个用户登录系统")
    for name, reply in responses:
        print(f"  [{name}] {reply}")

    print("\n--- 第二轮：@指定成员 ---")
    responses = room.round("@测试 你觉得测试方案怎么样？")
    for name, reply in responses:
        print(f"  [{name}] {reply}")

    print("\n--- 历史消息 ---")
    for m in room.history:
        tag = f"@{m.sender}" if m.kind == "dm" else m.sender
        print(f"  {tag}: {m.content[:60]}")

    print("\n✅ CodeTeam 路由层工作正常！")
    print("你只需要实现 AgentBackend 接口就可以接入任意 Agent。")


if __name__ == "__main__":
    main()
