# 03 — Python 速查：面向 Java 开发者

> 本文只讲这个项目中实际用到的 Python 特性。

---

## 类型系统

```python
# Java: String name;
name: str = "hello"

# Java: List<String> items;
items: list[str] = []

# Java: Map<String, int> scores;
scores: dict[str, int] = {}

# Java: Optional<String>
maybe: str | None = None        # Python 3.10+ 语法（旧写法：Optional[str]）

# Java: Pair<String, int>（没有内置，用 tuple 代替）
pair: tuple[str, int] = ("hello", 42)
text, num = pair               # 解包：text="hello", num=42
```

---

## 数据类（Pydantic BaseModel）

```python
# Java: @Data class Message { String role; String content; }
from pydantic import BaseModel

class Message(BaseModel):
    role: str
    content: str

# 创建实例（自动生成 __init__）
m = Message(role="user", content="hello")
# 访问字段
print(m.role)      # "user"
# JSON 序列化
print(m.model_dump())  # {"role": "user", "content": "hello"}
```

---

## 抽象类

```python
# Java: abstract class / interface
from abc import ABC, abstractmethod

class ModelClient(ABC):          # ABC = Abstract Base Class（类比 Java abstract class）
    @abstractmethod
    def stream(self, messages):  # 相当于 abstract 方法
        ...                      # 必须被子类实现，否则无法实例化

class OllamaClient(ModelClient):
    def stream(self, messages):  # 实现抽象方法
        yield ...
```

---

## async/await

```python
# Java: CompletableFuture<String> 或 Mono<String>
async def fetch_data() -> str:      # 声明为异步函数
    result = await some_async_call()  # 等待异步结果（不阻塞线程）
    return result

# 调用：
text = await fetch_data()
```

**关键区别：**
- Python 的 `async/await` 是单线程协作式并发（基于 `asyncio` 事件循环）
- Java 的 `CompletableFuture` 默认用线程池
- 效果类似，但 Python 版本语法更简洁

---

## async generator（最重要的概念）

```python
# 这是本项目最核心的 Python 特性
# Java 没有直接等价物，最接近的是 Reactor 的 Flux

async def stream_numbers():          # async generator function
    for i in range(10):
        await asyncio.sleep(0.1)     # 模拟异步 IO
        yield i                      # 产出一个值，暂停函数

# 消费：
async for num in stream_numbers():   # 每次 yield 都会触发一次循环体
    print(num)                       # 0, 1, 2, ... 9（每隔 0.1s）
```

**在项目中的应用：**

```python
# service/game.py - run_turn 是 async generator
async def run_turn(...) -> AsyncIterator[ParseEvent]:
    ...
    async for chunk in client.stream(msgs, params):  # 消费 LLM 流
        for ev in parser.feed(chunk.delta):
            yield ev                                  # 产出解析事件

# api/turn.py - API 路由消费 run_turn
async for ev in run_turn(s, session_id, body.action, client):
    if isinstance(ev, NarrativeDelta):
        yield {"event": "narrative", "data": ...}    # 再次 yield 给 SSE
```

---

## 列表推导式 / 生成器表达式

```python
# Java: list.stream().filter(...).map(...).collect(...)
names = [npc.name for npc in npcs if npc.state == "active"]
# 等价于：
names = []
for npc in npcs:
    if npc.state == "active":
        names.append(npc.name)

# any() 短路检测（类比 stream().anyMatch()）
has_enter = any(t.name == "location_enter" for t in completed_tags)
```

---

## 字符串 f-string

```python
# Java: String.format("Hello %s, you have %d HP", name, hp)
# 或 "Hello " + name + ", you have " + hp + " HP"

name = "Riku"
hp = 20
msg = f"Hello {name}, you have {hp} HP"   # f-string：大括号里可以放任意表达式
msg2 = f"总计：{hp * 2} 点"               # 支持表达式计算
```

---

## 常用内置函数

```python
# 字典的安全取值（带默认值）
value = my_dict.get("key", "default")   # Java: map.getOrDefault("key", "default")

# 列表合并字符串
result = "".join(["a", "b", "c"])       # → "abc"  （Java: String.join("", list)）

# 解包（展开）运算符
merged = {**dict1, **dict2}             # 合并两个字典（后者覆盖前者）
combined = [*list1, *list2]             # 合并两个列表
```

---

## 上下文管理器（with 语句）

```python
# Java: try-with-resources (AutoCloseable)
# Python: with 语句（上下文管理器）

# 数据库会话（自动关闭）
async with session_maker() as s:
    sess = await s.get(GameSession, session_id)
    ...
    await s.commit()
# 离开 with 块时自动关闭 session，即使发生异常也不会泄漏

# 文件操作
with open("file.txt") as f:
    content = f.read()
# 离开 with 块时自动 close()
```

---

## 装饰器（Decorator）

```python
# 装饰器 = 包裹函数的函数（类比 Java 的注解，但功能更强，在运行时执行）

@router.post("/{session_id}/turn")    # 注册为 POST 路由
async def take_turn(session_id: int, body: TurnRequest):
    ...

@pytest.mark.asyncio                  # 标记为异步测试
async def test_run_turn():
    ...

# 等价展开写法（帮助理解）：
async def take_turn(...): ...
take_turn = router.post("/{session_id}/turn")(take_turn)
```

---

## 学习路线建议

根据你的 Java 背景，建议按这个顺序学习：

**第一周：Python 基础语法**
- 类型注解（本文上面的内容）
- `dataclass` / Pydantic
- 列表推导式、字典
- f-string

**第二周：异步编程**
- `asyncio` 基础（事件循环的概念）
- `async/await`
- **async generator**（本项目最核心的概念，必须掌握）

**第三周：Web 框架**
- FastAPI 快速入门（官方教程很好）
- SQLAlchemy 2.0 async 模式
- Pydantic v2

**第四周：LLM 工程化**
- OpenAI API 调用
- 流式响应（streaming）
- Prompt Engineering 基础
- 看 [02-LLM工程化](02-llm-engineering.md)

**推荐资源：**
- Python 官方文档（asyncio 部分）
- FastAPI 官方文档（最好的 FastAPI 教程）
- SQLAlchemy 2.0 docs（注意区分 1.x 和 2.x，语法有变化）
- Pydantic v2 docs
