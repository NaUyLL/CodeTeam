"""pytest fixtures for CodeTeam routing tests"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
import tempfile
import os

from codeteam.core.backend import AgentBackend
from codeteam.room import Room, AgentMember, RoomMessage


# ═══════════════════════════════════════════════════════════════
# Mock AgentBackend
# ═══════════════════════════════════════════════════════════════

class MockBackend(AgentBackend):
    """可控的 mock backend，测试用"""

    def __init__(self, act_result: str = "", decide_result: bool = True,
                 system_prompt: str = "测试助手"):
        self._act_result = act_result
        self._decide_result = decide_result
        self._system_prompt = system_prompt

    def act(self, instruction: str) -> str:
        return self._act_result

    def decide(self, context: str) -> bool:
        return self._decide_result

    def get_system_prompt(self) -> str:
        return self._system_prompt

    def to_dict(self) -> dict:
        return {"type": "mock", "system_prompt": self._system_prompt}

    @classmethod
    def from_dict(cls, data: dict, **kwargs) -> MockBackend:
        return cls(system_prompt=data.get("system_prompt", ""))


class AlwaysYESBackend(MockBackend):
    """总是举手"""
    def __init__(self, act_result: str = "我同意", system_prompt: str = "活跃成员"):
        super().__init__(act_result=act_result, decide_result=True,
                         system_prompt=system_prompt)


class AlwaysNOBackend(MockBackend):
    """从不举手"""
    def __init__(self, system_prompt: str = "沉默成员"):
        super().__init__(act_result="", decide_result=False,
                         system_prompt=system_prompt)


class MagicBackend(AgentBackend):
    """完全由 MagicMock 驱动的 backend（最灵活）"""

    def __init__(self):
        self.mock = MagicMock(spec=AgentBackend)
        self.mock.act.return_value = ""
        self.mock.decide.return_value = True
        self.mock.get_system_prompt.return_value = "测试"
        self.mock.to_dict.return_value = {"type": "magic"}

    def act(self, instruction: str) -> str:
        return self.mock.act(instruction)

    def decide(self, context: str) -> bool:
        return self.mock.decide(context)

    def get_system_prompt(self) -> str:
        return self.mock.get_system_prompt()

    def to_dict(self) -> dict:
        return self.mock.to_dict()

    @classmethod
    def from_dict(cls, data: dict, **kwargs) -> MagicBackend:
        return cls()


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def yes_backend():
    return AlwaysYESBackend()


@pytest.fixture
def no_backend():
    return AlwaysNOBackend()


@pytest.fixture
def silent_backend():
    return MockBackend(act_result="", decide_result=False)


@pytest.fixture
def magic_backend():
    return MagicBackend()


@pytest.fixture
def room(yes_backend, silent_backend):
    """含 Alice(举手) 和 Bob(沉默) 的 2 人 Room"""
    room = Room("测试会议室")
    room.register(AgentMember("Alice", "测试助手", yes_backend))
    room.register(AgentMember("Bob", "测试助手", silent_backend))
    return room


@pytest.fixture
def room_3agents(yes_backend, silent_backend, no_backend):
    """含 Alice(YES) / Bob(空) / Charlie(NO) 的 3 人 Room"""
    room = Room("三人测试室")
    room.register(AgentMember("Alice", "活跃成员", yes_backend))
    room.register(AgentMember("Bob", "中性成员", silent_backend))
    room.register(AgentMember("Charlie", "沉默成员", no_backend))
    return room


@pytest.fixture
def room_with_dm():
    """用于私信测试的 Room（带 magic backend）"""
    room = Room("私信测试室")

    alice = MagicBackend()
    alice.mock.act.return_value = "收到私信，明白"
    alice_member = AgentMember("Alice", "测试助手", alice, on_pass="PASS")

    bob = MagicBackend()
    bob.mock.act.return_value = "已收到 Alice 的消息"
    bob_member = AgentMember("Bob", "测试助手", bob, on_pass="PASS")

    room.register(alice_member)
    room.register(bob_member)
    return room


# ═══════════════════════════════════════════════════════════════
# RoomMessage
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def sample_messages():
    return [
        RoomMessage(sender="user", content="大家好", timestamp=100.0),
        RoomMessage(sender="Alice", content="你好", timestamp=101.0),
        RoomMessage(sender="Bob", content="嗨", timestamp=102.0, kind="dm"),
    ]


# ═══════════════════════════════════════════════════════════════
# 临时文件系统
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_workspace():
    """创建临时工作目录，测试完自动清理"""
    with tempfile.TemporaryDirectory(prefix="codeteam_test_") as tmpdir:
        orig_cwd = os.getcwd()
        os.chdir(tmpdir)
        yield tmpdir
        os.chdir(orig_cwd)
