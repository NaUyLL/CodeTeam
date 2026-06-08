# CodeTeam 架构文档

## 设计哲学

**CodeTeam 不做 Agent，只做路由。**

我们把多 Agent 协作拆成两层：

```
┌──────────────────┐
│   传输层          │  Gateway — CLI / HTTP / 飞书 ...
│   谁在说话        │
├──────────────────┤
│   会话层          │  Room — 排队、举手、发言、@mention
│   谁在等、谁在说  │
├──────────────────┤
│   接口层          │  AgentBackend — 你来填
│   谁来干活        │
└──────────────────┘
```

## 为什么拆

CollabRoom 把 Agent 实现（CoreAgent、LLM、Memory、Tool）和路由（Room、AgentMember）写在一起。结果是：

- 想换底层 Agent → 改 Room
- 想测试路由逻辑 → 必须 mock 整个 CoreAgent
- 外部 Agent（OpenCode、Codex）无法直接接入

CodeTeam 全剥离了。路由就是路由，Agent 就是 Agent。

## 接口定义

```python
class AgentBackend(ABC):
    def act(self, instruction: str) -> str       # 执行指令，返回回复
    def decide(self, context: str) -> bool        # 轻量决策：要不要发言
    def get_system_prompt(self) -> str            # 系统提示
    def to_dict(self) -> dict                     # 序列化
    @classmethod from_dict(cls, data, **kwargs)   # 反序列化
```

只需要实现这 5 个方法，你的 Agent 就能接入 Room。

## 文件职责

| 文件 | 职责 |
|------|------|
| `room.py` | Room 编排 + AgentMember 调度 |
| `core/backend.py` | AgentBackend 抽象接口 |
| `core/logger.py` | 结构化 JSON 日志 |
| `gateway/__init__.py` | BaseGateway 抽象 |
| `gateway/cli.py` | 终端交互 |
| `gateway/http.py` | HTTP API + Web UI |

## 与 CollabRoom 的关系

```
CollabRoom = CodeTeam + CoreAgent(LLM/Memory/Tool)
CodeTeam   = 路由层（25% 代码量）
```

CollabRoom 是完整的多 Agent 开发框架（开箱即用）。
CodeTeam 是它的路由层内核（你自己配 Agent）。
