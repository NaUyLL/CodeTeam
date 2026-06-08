"""Room — 会议室：管理多个 Agent 实例，协调消息路由与多轮对话

交互机制：
  用户发言
    ① 举手阶段 — 每个 Agent 轻量决策 YES/NO
        无人举手 → 兜底强制选一个
    ② 发言阶段 — 举手者依次发言
        发言中 @某Agent → 强制该 Agent 回应（防循环）
    ③ 用户停止词 → 本轮中断
"""

from __future__ import annotations
import json, re, time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from codeteam.core.backend import AgentBackend
from codeteam.core.logger import get_logger, get_trace_id

logger = get_logger("room")

# ── 常量 ──
STOP_WORDS = {"停止", "够了", "停", "别说了", "结束", "到此为止",
              "stop", "enough", "halt", "打住"}
# _is_stop 使用完整匹配（非子串匹配），避免误触发
STOP_MATCH_WHOLE_WORD = True
MAX_AUTO_DEPTH = 5       # 一轮用户发言内最大自动交互次数
MAX_PAIR_LOOPS = 2       # 同一对 Agent 来回 @ 的最大次数
# 支持中英文 @mention：@名字 后跟空格、标点或结尾
MENTION_RE = re.compile(r'@(\S+?)(?=[\s:：，。！？、；\n]|$)')


@dataclass
class RoomMessage:
    """房间中的一条消息"""
    sender: str
    content: str
    timestamp: float = 0.0
    kind: str = "public"  # "public" | "dm"

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class AgentMember:
    """一个 Agent 成员 — 通过 AgentBackend 底层干活，Room 层统一调度"""

    def __init__(self, name: str, role_desc: str,
                 backend: AgentBackend,
                 on_pass: str | None = "PASS"):
        assert isinstance(backend, AgentBackend), \
            f"backend 必须是 AgentBackend 实例，得到 {type(backend).__name__}"
        self.name = name
        self.role_desc = role_desc
        self.backend = backend
        self.on_pass = on_pass
        self._system_prompt = (
            f"你叫 {name}，你的角色是：{role_desc}\n"
            f"{backend.get_system_prompt()}"
        )

    def decide(self, context: str) -> bool:
        """轻量决策：根据当前上下文，判断自己是否要发言。"""
        return self.backend.decide(context)

    def chat(self, context: str, mention_context: str | None = None,
             force_reply: bool = False) -> str:
        """Agent 发言。force_reply=True 时绕过 PASS 提示（兜底场景）。"""
        msg = f"【房间对话上下文】\n{context}\n\n"
        if mention_context:
            msg += f"{mention_context}\n\n"
        if force_reply:
            msg += (
                f"现在轮到 {self.name} 切实行动：\n"
                f"1. 需要讨论分析就直接说出来\n"
                f"2. 需要执行任务（修改代码、运行命令等）就直接用你的工具去执行\n"
                f"完成后给出最终回复。"
            )
        else:
            msg += f"现在轮到 {self.name} 发言。"
            if self.on_pass is not None:
                msg += f" 如果你觉得没什么可说的，只回复「{self.on_pass}」。"
        return self.backend.act(msg)

    # ── 序列化 ────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化 AgentMember 状态"""
        return {
            "name": self.name,
            "role_desc": self.role_desc,
            "on_pass": self.on_pass,
            "system_prompt": self._system_prompt,
            "backend": self.backend.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict, **kwargs) -> AgentMember:
        """从字典重建 AgentMember，需传入 backend 或 make_backend

        kwargs:
            make_backend: Callable[[dict], AgentBackend] — 根据序列化数据重建 backend
            或直接传入 backend: AgentBackend
        """
        backend = kwargs.get("backend")
        make_backend = kwargs.get("make_backend")
        if not backend and make_backend:
            backend = make_backend(data.get("backend", {}))
        if not backend:
            raise ValueError("from_dict 需要 backend 或 make_backend 参数")

        member = cls(
            name=data["name"],
            role_desc=data["role_desc"],
            backend=backend,
            on_pass=data.get("on_pass"),
        )
        sp = data.get("system_prompt", backend.get_system_prompt())
        member._system_prompt = sp
        return member


class Room:
    """会议室 — 管理一组 Agent，协调多人对话"""

    def __init__(self, name: str = "会议室"):
        self.name = name
        self.members: dict[str, AgentMember] = {}
        self.history: list[RoomMessage] = []
        self._order: list[str] = []

    def register(self, member: AgentMember, position: int | None = None):
        self.members[member.name] = member
        if position is not None:
            self._order.insert(position, member.name)
        else:
            self._order.append(member.name)

    def say(self, sender: str, content: str,
            kind: str = "public") -> RoomMessage:
        msg = RoomMessage(sender=sender, content=content, kind=kind)
        self.history.append(msg)
        return msg

    def format_history(self, tail: int = 10,
                       include_kind: set[str] | None = None) -> str:
        msgs = self.history
        if include_kind:
            msgs = [m for m in msgs if m.kind in include_kind]
        lines = []
        for m in msgs[-tail:]:
            tag = f"@{m.sender}" if m.kind == "dm" else m.sender
            # 截断长内容，保留关键信息
            content = m.content[:250]
            if len(m.content) > 250:
                content += "…"
            lines.append(f"{tag}: {content}")
        return "\n".join(lines)

    # ── 核心交互 ──────────────────────────────────────

    def round(self, user_message: str) -> list[tuple[str, str]]:
        """用户发言 → 举手 → 发言 → @mention 链式回应 → 停止检测"""
        # 停止词检测
        if self._is_stop(user_message):
            logger.info("room_stop", text=user_message[:100])
            return []

        self.say("user", user_message)
        responses: list[tuple[str, str]] = []

        context = self.format_history(tail=15)

        # ── Phase 1: 举手 ──
        volunteers = self._volunteer_round(context)

        # 用户 @某Agent → 强制加入举手名单，排最前面，走执行模式
        user_mentions = self._parse_mentions(user_message)
        user_mentioned = set(user_mentions)
        for name in self._order:  # 按注册顺序
            if name in user_mentioned and name in self.members:
                # 已在 volunteers 里的移到最前，不在的插入最前
                if name in volunteers:
                    volunteers.remove(name)
                volunteers.insert(0, name)
        had_volunteers = bool(volunteers)

        # 兜底：无人举手 → 强制选一个
        if not volunteers:
            fallback = self._pick_fallback()
            if fallback:
                volunteers = [fallback]

        # ── Phase 2: 发言 + @mention 链式回应 ──
        pair_counts: dict[tuple[str, str], int] = {}
        queue = list(volunteers)
        no_volunteers = not had_volunteers
        depth = 0

        while queue and depth < MAX_AUTO_DEPTH:
            speaker = queue.pop(0)
            member = self.members.get(speaker)
            if not member:
                continue

            context = self.format_history(tail=15)
            is_fallback = (no_volunteers and depth == 0)
            # 用户 @mention → 执行模式（force_reply + 含用户指令）
            is_user_direct = (speaker in user_mentioned and depth == 0)
            if is_user_direct:
                reply = member.chat(
                    context,
                    mention_context=f"【用户指定】用户 @了你并说：{user_message}",
                    force_reply=True,
                )
            else:
                reply = member.chat(context, force_reply=is_fallback)

            pass_reply = member.on_pass or "PASS"
            if not is_fallback and reply.strip() == pass_reply.strip():
                continue
            if not reply.strip():
                continue

            self.say(speaker, reply)
            responses.append((speaker, reply))
            depth += 1

            # 检查 @mention
            mentions = self._parse_mentions(reply)
            for target in mentions:
                if target not in self.members or target == speaker:
                    continue

                pair = tuple(sorted([speaker, target]))
                pair_counts[pair] = pair_counts.get(pair, 0) + 1
                if pair_counts[pair] > MAX_PAIR_LOOPS:
                    continue

                if target not in queue:
                    queue.insert(0, target)

        return responses

    def dm(self, from_name: str, to_name: str, content: str) -> str | None:
        """Agent 之间私信"""
        member = self.members.get(to_name)
        if not member:
            return None

        self.say(from_name, content, kind="dm")
        context = self.format_history(tail=5, include_kind={"public", "dm"})

        mention_context = f"【私信】@{from_name} 对你说：{content}"
        reply = member.chat(context, mention_context=mention_context)

        if member.on_pass and reply.strip() == member.on_pass.strip():
            return None

        self.say(to_name, reply, kind="dm")
        return reply

    def list_members(self) -> list[str]:
        return list(self.members.keys())

    # ── 内部方法 ────────────────────────────────────

    def _is_stop(self, msg: str) -> bool:
        """检测用户停止词 — 使用完整匹配，避免「停下来」误触「停」"""
        if STOP_MATCH_WHOLE_WORD:
            # 按空格/标点分词后精确匹配
            tokens = re.split(r'[\s，。！？、；：,.!?;:\n]+', msg.strip())
            return any(w in tokens for w in STOP_WORDS)
        return any(w in msg for w in STOP_WORDS)

    def _volunteer_round(self, context: str) -> list[str]:
        """并行举手：每个 Agent 决定是否要发言"""
        with ThreadPoolExecutor(max_workers=len(self._order) or 1) as executor:
            future_map = {
                executor.submit(self._decide_one, name, context): name
                for name in self._order
            }
            decided: dict[str, bool] = {}
            for future in as_completed(future_map):
                name = future_map[future]
                try:
                    decided[name] = future.result()
                except Exception as exc:
                    decided[name] = False
                    logger.warning("decision_error", member=name, error=str(exc))
        return [name for name in self._order if decided.get(name)]

    def _decide_one(self, name: str, context: str) -> bool:
        """单个 Agent 举手决策（可被子类重写）"""
        member = self.members.get(name)
        if not member:
            return False
        return member.decide(context)

    def _pick_fallback(self) -> str | None:
        """兜底：无人举手时强制选第一个 Agent"""
        return self._order[0] if self._order else None

    def _parse_mentions(self, text: str) -> list[str]:
        """解析 @某Agent 提及"""
        found = MENTION_RE.findall(text)
        seen = set()
        result = []
        for name in found:
            name = name.strip("@").strip()
            if name in self.members and name not in seen:
                seen.add(name)
                result.append(name)
        return result

    # ── 序列化（Session 持久化） ─────────────

    def save(self, path: str) -> str:
        """将 Room 完整状态序列化到 JSON 文件"""
        data = {
            "version": 1,
            "name": self.name,
            "members": {
                name: member.to_dict()
                for name, member in self.members.items()
            },
            "history": [
                {
                    "sender": m.sender,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "kind": m.kind,
                }
                for m in self.history
            ],
        }
        text = json.dumps(data, ensure_ascii=False, indent=2)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info("room_saved", path=path, members=len(self.members),
                     history=len(self.history))
        return text

    @classmethod
    def load(cls, path: str,
             make_backend: Callable[[dict], AgentBackend]) -> Room:
        """从 JSON 文件恢复 Room

        Args:
            path: JSON 文件路径
            make_backend: Callable[[dict], AgentBackend]
                          根据序列化数据重建 backend
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        version = data.get("version", 0)
        if version < 1:
            raise ValueError(f"不支持的 Session 版本: {version}")

        room = cls(name=data.get("name", "会议室"))

        for name, member_data in data.get("members", {}).items():
            backend = make_backend(member_data.get("backend", {}))
            member = AgentMember.from_dict(member_data, backend=backend)
            room.register(member)

        # 恢复对话历史
        for h in data.get("history", []):
            msg = RoomMessage(
                sender=h["sender"],
                content=h["content"],
                timestamp=h.get("timestamp", 0.0),
                kind=h.get("kind", "public"),
            )
            room.history.append(msg)

        logger.info("room_loaded", path=path, members=len(room.members),
                     history=len(room.history))
        return room
