# CodeTeam v0.1.0

**多 Agent 协作路由层** — 只做路由，不做实现。

## 设计哲学

CodeTeam 是一个**纯路由层**框架，专注于多 Agent 对话的编排与调度，**不做单个 Agent 的实现**。

```
┌──────────────────────────────┐
│  Gateway  （传输层）          │
│  CLI / HTTP 接入             │
├──────────────────────────────┤
│  Room     （会话层）          │
│  管理多个 Agent 实例         │
│  协调举手、发言、@mention    │
│  防循环、停止词检测          │
├──────────────────────────────┤
│  AgentBackend  (接口)        │
│  你来实现: act/decide        │
│  CoreAgent / OpenCode / 人   │
└──────────────────────────────┘
```

## 核心交互机制

用户发言后 Room 自动执行：

1. **举手阶段** — 每个 Agent 决定是否要发言
2. **发言阶段** — 举手的 Agent 轮流发言
3. **@mention 链式回应** — Agent 发言中 @其他Agent 自动触发回应
4. **防循环** — 同一对 Agent 来回 @ 最多 2 次，单轮总深度最多 5 次
5. **停止词** — 用户输入「够了」「停止」「结束」截断本轮

## 快速开始

```python
from codeteam import Room, AgentMember, AgentBackend

# 实现你的 AgentBackend
class MyAgent(AgentBackend):
    def act(self, instruction: str) -> str:
        return "你好，我是 Agent！"
    def get_system_prompt(self) -> str:
        return "你是助手"
    def to_dict(self):
        return {"type": "my"}
    @classmethod
    def from_dict(cls, data, **kwargs):
        return cls()

# 创建 Room 并注册
room = Room("讨论室")
room.register(AgentMember("助手", "测试助手", MyAgent()))
responses = room.round("大家好")
print(responses)
```

## 文件结构

```
codeteam/
├── __init__.py      # Room, AgentMember, AgentBackend
├── room.py          # Room + AgentMember（核心）
├── core/
│   ├── backend.py   # AgentBackend 抽象接口
│   └── logger.py    # 结构化日志
├── gateway/
│   ├── __init__.py  # BaseGateway 抽象
│   ├── cli.py       # CLI 交互
│   └── http.py      # HTTP + Web UI
├── examples/
│   └── minimal_demo.py
└── tests/
    ├── test_room.py
    └── test_session.py
```

## 与 CollabRoom 的关系

CodeTeam 是 CollabRoom 的反向提取：
- **CollabRoom** = CodeTeam + CoreAgent（完整的 Agent 实现框架）
- **CodeTeam** = 纯路由层（AgentBackend 接口 + Room 编排）

如果你想要一个**开箱即用的多 Agent 开发团队**，用 CollabRoom。
如果你想要**自己实现 Agent**、或者把 OpenCode/Codex 等接入多 Agent 协作，用 CodeTeam。

## License

MIT
