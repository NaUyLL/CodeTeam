"""测试 Room 模块 — RoomMessage / Room / AgentMember"""
from __future__ import annotations
import time
from unittest.mock import MagicMock, patch

import pytest

from codeteam.room import (
    RoomMessage, Room, AgentMember,
    STOP_WORDS, STOP_MATCH_WHOLE_WORD,
    MAX_AUTO_DEPTH, MAX_PAIR_LOOPS, MENTION_RE,
)
from codeteam.core.backend import AgentBackend

from .conftest import MockBackend, AlwaysYESBackend, AlwaysNOBackend, MagicBackend


# ═══════════════════════════════════════════════════════════════
# RoomMessage
# ═══════════════════════════════════════════════════════════════

class TestRoomMessage:
    """RoomMessage 数据类测试"""

    def test_创建消息并指定所有字段(self):
        msg = RoomMessage(sender="Alice", content="你好", timestamp=100.0, kind="dm")
        assert msg.sender == "Alice"
        assert msg.content == "你好"
        assert msg.timestamp == 100.0
        assert msg.kind == "dm"

    def test_timestamp自动填充为0时自动设当前时间(self):
        with patch("codeteam.room.time.time", return_value=1234.567):
            msg = RoomMessage(sender="Bob", content="嗨")
        assert msg.timestamp == 1234.567

    def test_timestamp为非零时不覆盖(self):
        msg = RoomMessage(sender="Bob", content="嗨", timestamp=42.0)
        assert msg.timestamp == 42.0

    def test_kind默认值为public(self):
        msg = RoomMessage(sender="user", content="大家好")
        assert msg.kind == "public"


# ═══════════════════════════════════════════════════════════════
# Room 初始化 & 基础方法
# ═══════════════════════════════════════════════════════════════

class TestRoomInit:
    """Room 初始化测试"""

    def test_初始化默认name(self):
        room = Room()
        assert room.name == "会议室"
        assert room.members == {}
        assert room.history == []
        assert room._order == []

    def test_初始化自定义name(self):
        room = Room("开发讨论")
        assert room.name == "开发讨论"


class TestRoomRegister:
    """Room.register() 成员注册测试"""

    def test_注册成员到末尾(self, yes_backend):
        room = Room("测试室")
        member = AgentMember("Alice", "测试助手", yes_backend)
        room.register(member)
        assert "Alice" in room.members
        assert room.members["Alice"] is member
        assert room._order == ["Alice"]

    def test_注册多个成员按顺序排列(self, yes_backend, silent_backend):
        room = Room("测试室")
        room.register(AgentMember("Alice", "助手A", yes_backend))
        room.register(AgentMember("Bob", "助手B", silent_backend))
        assert room._order == ["Alice", "Bob"]

    def test_指定position注册(self, yes_backend, silent_backend, no_backend):
        room = Room("测试室")
        room.register(AgentMember("Alice", "助手A", yes_backend))
        room.register(AgentMember("Charlie", "助手C", no_backend))
        room.register(AgentMember("Bob", "助手B", silent_backend), position=1)
        assert room._order == ["Alice", "Bob", "Charlie"]


class TestRoomSay:
    """Room.say() 添加消息测试"""

    def test_say添加public消息(self):
        room = Room()
        msg = room.say("user", "你好")
        assert len(room.history) == 1
        assert room.history[0].sender == "user"
        assert room.history[0].content == "你好"
        assert room.history[0].kind == "public"
        assert msg is room.history[0]

    def test_say添加dm消息(self):
        room = Room()
        msg = room.say("Alice", "秘密消息", kind="dm")
        assert msg.kind == "dm"


class TestRoomFormatHistory:
    """Room.format_history() 历史格式化测试"""

    def test_默认tail10条消息(self):
        room = Room()
        for i in range(15):
            room.say(f"user{i}", f"消息{i}")
        output = room.format_history()
        lines = output.split("\n")
        assert len(lines) == 10
        assert "user5" in output
        assert "user4" not in output
        assert "user14" in output

    def test_自定义tail参数(self):
        room = Room()
        for i in range(5):
            room.say(f"user{i}", f"消息{i}")
        output = room.format_history(tail=3)
        lines = output.split("\n")
        assert len(lines) == 3
        assert "user4" in output

    def test_kind过滤只包含public(self):
        room = Room()
        room.say("user", "公开消息", kind="public")
        room.say("Alice", "私信", kind="dm")
        room.say("Bob", "公开回复", kind="public")
        output = room.format_history(include_kind={"public"})
        assert "公开消息" in output
        assert "公开回复" in output
        assert "私信" not in output

    def test_kind过滤只包含dm(self):
        room = Room()
        room.say("user", "公开消息", kind="public")
        room.say("Alice", "私信", kind="dm")
        output = room.format_history(include_kind={"dm"})
        assert "公开消息" not in output
        assert "私信" in output

    def test_内容超过250字截断(self):
        room = Room()
        long_text = "x" * 300
        room.say("user", long_text)
        output = room.format_history()
        assert "x" * 250 + "…" in output
        assert len(output.split(": ", 1)[1].rstrip()) == 251

    def test_私信消息带at前缀(self):
        room = Room()
        room.say("Alice", "你好", kind="dm")
        output = room.format_history()
        assert "@Alice:" in output

    def test_public消息不带at前缀(self):
        room = Room()
        room.say("Alice", "你好", kind="public")
        output = room.format_history()
        assert "Alice:" in output
        assert "@Alice:" not in output


class TestRoomListMembers:
    """Room.list_members() 测试"""

    def test_空房间返回空列表(self):
        room = Room()
        assert room.list_members() == []

    def test_有成员时返回名字列表(self, yes_backend, silent_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        room.register(AgentMember("Bob", "助手", silent_backend))
        assert room.list_members() == ["Alice", "Bob"]


# ═══════════════════════════════════════════════════════════════
# _is_stop — 停止词检测
# ═══════════════════════════════════════════════════════════════

class TestIsStop:
    """Room._is_stop() 停止词检测"""

    def test_停止词_停止_返回True(self):
        room = Room()
        assert room._is_stop("停止") is True

    def test_停止词_够了_返回True(self):
        room = Room()
        assert room._is_stop("够了") is True

    def test_停止词_stop_返回True(self):
        room = Room()
        assert room._is_stop("stop") is True

    def test_停止词_enough_返回True(self):
        room = Room()
        assert room._is_stop("enough") is True

    def test_停止词_停_返回True(self):
        room = Room()
        assert room._is_stop("停") is True

    def test_停止词_停下来_返回False(self):
        room = Room()
        assert room._is_stop("停下来") is False

    def test_普通语句_返回False(self):
        room = Room()
        assert room._is_stop("今天天气怎么样") is False
        assert room._is_stop("请帮我分析一下这个文件") is False

    def test_多个标点混入_正确分词(self):
        room = Room()
        assert room._is_stop("好的，停止。") is True
        assert room._is_stop("够了！别再说了") is True

    def test_停止词在STOP_WORDS集合中(self):
        assert "停止" in STOP_WORDS
        assert "够了" in STOP_WORDS
        assert "停" in STOP_WORDS
        assert "stop" in STOP_WORDS
        assert "enough" in STOP_WORDS
        assert "halt" in STOP_WORDS

    def test_完整匹配模式开关(self):
        assert STOP_MATCH_WHOLE_WORD is True

    def test_子串模式关闭时_包含停止词的词不触发(self):
        room = Room()
        assert room._is_stop("停车") is False

    def test_多token消息中含停止词(self):
        room = Room()
        assert room._is_stop("我觉得 够了 不用继续了") is True


# ═══════════════════════════════════════════════════════════════
# _parse_mentions — @mention 解析
# ═══════════════════════════════════════════════════════════════

class TestParseMentions:
    """Room._parse_mentions() @mention 解析测试"""

    def test_单个提及(self, yes_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        result = room._parse_mentions("@Alice 你好")
        assert result == ["Alice"]

    def test_多个提及(self, yes_backend, silent_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        room.register(AgentMember("Bob", "助手", silent_backend))
        result = room._parse_mentions("@Alice @Bob 大家好")
        assert result == ["Alice", "Bob"]

    def test_提及不存在的成员_过滤掉(self, yes_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        result = room._parse_mentions("@Charlie 你好")
        assert result == []

    def test_重复提及_去重(self, yes_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        result = room._parse_mentions("@Alice @Alice 你好")
        assert result == ["Alice"]

    def test_中文标点后_正确识别(self, yes_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        result = room._parse_mentions("@Alice，你好")
        assert result == ["Alice"]

    def test_中英文混用(self, yes_backend, silent_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        room.register(AgentMember("Bob", "助手", silent_backend))
        result = room._parse_mentions("@Alice，@Bob。你们好")
        assert result == ["Alice", "Bob"]

    def test_冒号后识别(self, yes_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        result = room._parse_mentions("@Alice: 你好")
        assert result == ["Alice"]

    def test_无提及返回空列表(self, yes_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        result = room._parse_mentions("大家好，今天天气不错")
        assert result == []

    def test_混合存在和不存在的成员(self, yes_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        result = room._parse_mentions("@Alice @Charlie 你好")
        assert result == ["Alice"]


# ═══════════════════════════════════════════════════════════════
# _volunteer_round — 并行举手
# ═══════════════════════════════════════════════════════════════

class TestVolunteerRound:
    """Room._volunteer_round() 并行举手测试"""

    def test_所有成员举手_全部返回(self):
        """所有 Agent 都回答 YES → 全部返回"""
        room = Room()
        room.register(AgentMember("Alice", "总有话说", AlwaysYESBackend()))
        room.register(AgentMember("Bob", "爱凑热闹", AlwaysYESBackend()))
        volunteers = room._volunteer_round("大家好")
        assert volunteers == ["Alice", "Bob"]

    def test_无成员举手_返回空列表(self, no_backend):
        room = Room()
        room.register(AgentMember("Alice", "沉默", no_backend))
        room.register(AgentMember("Bob", "不说话", no_backend))
        volunteers = room._volunteer_round("大家好")
        assert volunteers == []

    def test_混合举手_只返回举手者(self, yes_backend, no_backend):
        room = Room()
        room.register(AgentMember("Alice", "活跃", yes_backend))
        room.register(AgentMember("Bob", "沉默", no_backend))
        volunteers = room._volunteer_round("大家好")
        assert volunteers == ["Alice"]

    def test_空房间_返回空列表(self):
        room = Room()
        volunteers = room._volunteer_round("大家好")
        assert volunteers == []

    def test_决策异常_不影响其他成员(self, yes_backend):
        """某个 Agent 抛异常时被捕获，不影响其他成员"""
        room = Room()
        room.register(AgentMember("Alice", "活跃", yes_backend))

        # Bob 的 decide 会抛异常
        bob_backend = MagicBackend()
        bob_backend.mock.decide.side_effect = RuntimeError("挂掉了")
        bob = AgentMember("Bob", "有问题", bob_backend)
        room.register(bob)

        volunteers = room._volunteer_round("大家好")
        assert volunteers == ["Alice"]

    def test_结果按注册顺序排列(self, yes_backend, silent_backend):
        room = Room()
        room.register(AgentMember("Charlie", "最后举手", yes_backend))
        room.register(AgentMember("Alice", "第一个举手", yes_backend))
        room.register(AgentMember("Bob", "第二个举手", silent_backend))
        volunteers = room._volunteer_round("测试")
        assert volunteers == ["Charlie", "Alice"]


# ═══════════════════════════════════════════════════════════════
# _pick_fallback — 兜底选择
# ═══════════════════════════════════════════════════════════════

class TestPickFallback:
    """Room._pick_fallback() 兜底选择测试"""

    def test_有成员_返回第一个(self, yes_backend, silent_backend):
        room = Room()
        room.register(AgentMember("Alice", "助手", yes_backend))
        room.register(AgentMember("Bob", "助手", silent_backend))
        assert room._pick_fallback() == "Alice"

    def test_空房间_返回None(self):
        room = Room()
        assert room._pick_fallback() is None

    def test_单成员_返回该成员(self, silent_backend):
        room = Room()
        room.register(AgentMember("Solo", "独苗", silent_backend))
        assert room._pick_fallback() == "Solo"


# ═══════════════════════════════════════════════════════════════
# round — 完整对话轮次
# ═══════════════════════════════════════════════════════════════

class TestRound:
    """Room.round() 完整流程测试"""

    def test_用户停止词_返回空结果(self):
        room = Room()
        result = room.round("停止")
        assert result == []

    def test_用户说够了_返回空结果(self):
        room = Room()
        result = room.round("够了")
        assert result == []

    def test_停止词不加入history(self):
        room = Room()
        room.round("停止")
        assert len(room.history) == 0

    def test_正常发言_举手成员依次回应(self, room):
        responses = room.round("大家好，讨论一下")
        assert len(responses) >= 1
        assert responses[0][0] == "Alice"

    def test_用户at某Agent_强制加入(self, yes_backend):
        """用户 @Bob → Bob 即使不举手也被强制加入"""
        room = Room("提及测试")

        # Alice 举手，Bob 沉默但被 @强制发言
        alice = AgentMember("Alice", "活跃", yes_backend)
        bob = MagicBackend()
        bob.mock.act.return_value = "收到，我来说说"
        bob = AgentMember("Bob", "沉默", bob)

        room.register(alice)
        room.register(bob)

        responses = room.round("@Bob 你说说看")
        assert len(responses) >= 1
        # Bob 被 @，应当发言
        senders = [r[0] for r in responses]
        assert "Bob" in senders

    def test_无人举手且无_mention_兜底第一个(self, silent_backend):
        """无人举手 + 无 @ → 强制第一个 Agent 发言"""
        room = Room("兜底测试")
        alice = AgentMember("Alice", "助手",
                           MockBackend(act_result="好吧，我来说说", decide_result=False))
        bob = AgentMember("Bob", "助手", silent_backend)
        room.register(alice)
        room.register(bob)

        responses = room.round("有人说话吗")
        # 应该强制 Alice 发言
        assert len(responses) == 1
        assert responses[0][0] == "Alice"
        assert "我来说说" in responses[0][1]

    def test_PASS回复被忽略(self, yes_backend):
        """Agent 回复 PASS → 不加入历史"""
        room = Room()
        alice = AgentMember("Alice", "助手",
                           AlwaysYESBackend(act_result="PASS"))
        room.register(alice)
        responses = room.round("大家好")
        assert responses == []

    def test_mention_链式回应(self, yes_backend):
        """Alice @Bob → Bob 自动回应"""
        room = Room("链式测试")
        alice_backend = AlwaysYESBackend(act_result="@Bob 你说说")
        alice = AgentMember("Alice", "活泼", alice_backend)

        bob_backend = MagicBackend()
        bob_backend.mock.act.return_value = "好的，我来补充"

        room.register(alice)
        room.register(AgentMember("Bob", "被提及", bob_backend))

        responses = room.round("开始讨论")
        senders = [r[0] for r in responses]
        assert "Alice" in senders
        assert "Bob" in senders

    def test_mention_防循环(self, yes_backend, silent_backend):
        """同一对 Agent 来回 @ 超过 MAX_PAIR_LOOPS 次后终止"""
        room = Room("防循环测试")
        # Alice 总是 @Bob，Bob 总是 @Alice
        alice_backend = AlwaysYESBackend(act_result="@Bob 你说")
        bob_backend = AlwaysYESBackend(act_result="@Alice 你说")

        alice = AgentMember("Alice", "A", alice_backend)
        bob = AgentMember("Bob", "B", bob_backend)

        room.register(alice)
        room.register(bob)

        responses = room.round("开始")
        # @Alice→@Bob→@Alice→@Bob→@Alice→... 最多 2 对 = 4 次交互
        # 但 MAX_AUTO_DEPTH=5 也会限制总深度
        assert len(responses) <= MAX_AUTO_DEPTH + 2

    def test_深度限制(self, yes_backend, silent_backend):
        """总深度超过 MAX_AUTO_DEPTH 时截断"""
        room = Room("深度截断")
        # 注册 6 个举手 agent
        for i in range(6):
            backend = AlwaysYESBackend(act_result=f"我是{i}号")
            room.register(AgentMember(f"Agent{i}", f"助手{i}", backend))

        responses = room.round("各抒己见")
        # 最多 MAX_AUTO_DEPTH=5 个发言
        assert len(responses) <= MAX_AUTO_DEPTH

    def test_dm私信(self, room_with_dm):
        """Agent 之间发送私信"""
        room = room_with_dm
        reply = room.dm("user", "Alice", "秘密消息")
        assert reply is not None
        assert len(reply) > 0

    def test_dm到不存在的成员(self, room_with_dm):
        """私信给不存在的成员 → None"""
        reply = room_with_dm.dm("user", "Charlie", "嗨")
        assert reply is None

    def test_dm时PASS_返回None(self):
        """目标 Agent 回复 PASS → dm 返回 None"""
        room = Room("DM-PASS")
        backend = AlwaysYESBackend(act_result="PASS")
        member = AgentMember("Alice", "助手", backend, on_pass="PASS")
        room.register(member)
        reply = room.dm("user", "Alice", "你好")
        assert reply is None

    def test_round_at用户_执行模式(self, yes_backend):
        """用户 @某Agent → force_reply=True 绕过 PASS"""
        room = Room("at用户测试")
        alice = AgentMember("Alice", "助手",
                           AlwaysYESBackend(act_result="好的，我来执行"))
        room.register(alice)
        responses = room.round("@Alice 干活了")
        assert len(responses) > 0
        assert responses[0][0] == "Alice"

    def test_空房间返回空列表(self):
        room = Room()
        responses = room.round("有人吗")
        assert responses == []


# ═══════════════════════════════════════════════════════════════
# AgentMember
# ═══════════════════════════════════════════════════════════════

class TestAgentMember:
    """AgentMember 基本功能测试"""

    def test_创建成员(self, yes_backend):
        member = AgentMember("Alice", "助手", yes_backend)
        assert member.name == "Alice"
        assert member.role_desc == "助手"
        assert member.backend is yes_backend
        assert member.on_pass == "PASS"

    def test_custom_on_pass(self, silent_backend):
        member = AgentMember("Bob", "助手", silent_backend, on_pass="跳过")
        assert member.on_pass == "跳过"

    def test_on_pass_None(self, silent_backend):
        member = AgentMember("Bob", "助手", silent_backend, on_pass=None)
        assert member.on_pass is None

    def test_decide(self, yes_backend, no_backend):
        assert AgentMember("Alice", "助手", yes_backend).decide("你好") is True
        assert AgentMember("Bob", "助手", no_backend).decide("你好") is False

    def test_chat(self):
        backend = MockBackend(act_result="回复内容")
        member = AgentMember("Alice", "助手", backend)
        reply = member.chat("上下文")
        assert "回复内容" in reply

    def test_chat_with_mention_context(self):
        backend = MockBackend(act_result="明白")
        member = AgentMember("Alice", "助手", backend)
        reply = member.chat("上下文", mention_context="@Alice 说详情")
        assert "明白" in reply

    def test_chat_force_reply(self):
        """force_reply=True 模式下生成包含 '切实行动' 的指令"""
        backend = MockBackend(act_result="好的，执行")
        member = AgentMember("Alice", "助手", backend)
        reply = member.chat("上下文", force_reply=True)
        assert "好的" in reply

    def test_chat_PASS_ignore(self):
        backend = MockBackend(act_result="PASS")
        member = AgentMember("Alice", "助手", backend, on_pass="PASS")
        reply = member.chat("上下文")
        assert reply == "PASS"

    def test_type_check_backend(self):
        """backend 必须是 AgentBackend 实例"""
        with pytest.raises(AssertionError):
            AgentMember("Bad", "bad", "not_a_backend")

    def test_system_prompt_contains_name(self, yes_backend):
        member = AgentMember("Alice", "测试助手", yes_backend)
        assert "Alice" in member._system_prompt
        assert "测试助手" in member._system_prompt


# ═══════════════════════════════════════════════════════════════
# AgentMember 序列化
# ═══════════════════════════════════════════════════════════════

class TestAgentMemberSerialization:
    """AgentMember.to_dict / from_dict"""

    def test_to_dict_includes_fields(self, yes_backend):
        member = AgentMember("Alice", "测试助手", yes_backend, on_pass="PASS")
        d = member.to_dict()
        assert d["name"] == "Alice"
        assert d["role_desc"] == "测试助手"
        assert d["on_pass"] == "PASS"
        assert "system_prompt" in d
        assert "backend" in d

    def test_from_dict_with_direct_backend(self, yes_backend):
        member = AgentMember("Alice", "助手", yes_backend)
        data = member.to_dict()
        restored = AgentMember.from_dict(data, backend=yes_backend)
        assert restored.name == "Alice"
        assert restored.role_desc == "助手"

    def test_from_dict_with_make_backend(self, yes_backend):
        member = AgentMember("Alice", "助手", yes_backend)
        data = member.to_dict()

        def make_backend(bd):
            return MockBackend(system_prompt=bd.get("system_prompt", ""))

        restored = AgentMember.from_dict(data, make_backend=make_backend)
        assert restored.name == "Alice"

    def test_from_dict_no_backend_raises(self):
        with pytest.raises(ValueError, match="backend"):
            AgentMember.from_dict({"name": "X", "role_desc": "", "backend": {}})

    def test_from_dict_restores_system_prompt(self):
        bk = MockBackend(system_prompt="原始提示")
        member = AgentMember("Alice", "助手", bk)

        # 保存并篡改 system_prompt
        data = member.to_dict()
        data["system_prompt"] = "自定义提示"

        restored = AgentMember.from_dict(data, backend=bk)
        assert restored._system_prompt == "自定义提示"


# ═══════════════════════════════════════════════════════════════
# Room 序列化 — save
# ═══════════════════════════════════════════════════════════════

class TestRoomSave:
    """Room.save()"""

    def _setup_room(self):
        room = Room("测试室")
        room.register(AgentMember("Alice", "助手A",
                                  MockBackend(act_result="你好", system_prompt="助手A")))
        room.register(AgentMember("Bob", "助手B",
                                  MockBackend(act_result="嗨", system_prompt="助手B")))
        room.say("user", "你好")
        room.say("Alice", "你好，有什么需要帮助的？")
        room.say("user", "今天天气怎么样")
        room.say("Bob", "今天天气不错")
        return room

    def test_save_creates_file(self):
        room = self._setup_room()
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            room.save(path)
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
        finally:
            os.unlink(path)

    def test_save_json_structure(self):
        room = self._setup_room()
        import tempfile, os, json
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            text = room.save(path)
            data = json.loads(text)
            assert data["version"] == 1
            assert data["name"] == "测试室"
            assert len(data["members"]) == 2
            assert len(data["history"]) == 4
            for name, m in data["members"].items():
                assert "name" in m
                assert "role_desc" in m
                assert "backend" in m
            for h in data["history"]:
                assert "sender" in h
                assert "content" in h
                assert "kind" in h
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════
# Room 序列化 — load
# ═══════════════════════════════════════════════════════════════

class TestRoomLoad:
    """Room.load()"""

    def _setup_and_save(self):
        room = Room("测试室")
        room.register(AgentMember("Alice", "助手A",
                                  MockBackend(act_result="你好", system_prompt="助手A")))
        room.register(AgentMember("Bob", "助手B",
                                  MockBackend(act_result="嗨", system_prompt="助手B")))
        room.say("user", "你好")
        room.say("Alice", "你好，有什么需要帮助的？")
        room.say("user", "今天天气怎么样")
        room.say("Bob", "今天天气不错")

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        room.save(path)
        return path

    def test_load_full_round_trip(self):
        path = self._setup_and_save()
        import os
        try:
            def make_backend(data):
                return MockBackend(system_prompt=data.get("system_prompt", ""))
            restored = Room.load(path, make_backend=make_backend)
            assert restored.name == "测试室"
            assert len(restored.members) == 2
            assert len(restored.history) == 4
            assert restored.history[0].sender == "user"
            assert restored.history[0].content == "你好"
        finally:
            os.unlink(path)

    def test_load_history_content(self):
        path = self._setup_and_save()
        import os
        try:
            def make_backend(data):
                return MockBackend(system_prompt=data.get("system_prompt", ""))
            restored = Room.load(path, make_backend=make_backend)
            assert restored.history[1].content == "你好，有什么需要帮助的？"
        finally:
            os.unlink(path)

    def test_load_version_check(self):
        path = self._setup_and_save()
        import os, json
        try:
            with open(path) as f:
                data = json.load(f)
            data["version"] = 0
            with open(path, "w") as f:
                json.dump(data, f)

            with pytest.raises(ValueError, match="版本"):
                Room.load(path, make_backend=lambda d: MockBackend())
        finally:
            os.unlink(path)
