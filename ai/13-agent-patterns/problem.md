# Topic 13: the four agent patterns

## The prompt

> "Name the agent architectures you know, and tell me when each one is the right choice —
> and when it isn't."

## Clarifying questions worth asking back

1. "Are the steps known in advance?" — this single question picks the pattern.
2. "Is there a verifiable success signal?" — decides whether reflection can work at all.
3. "How much latency and cost budget per task?" — ReAct is the most expensive shape.

## The follow-up bank

1. ReAct vs plan-and-execute — which and why?
2. Why does reflection often fail to improve anything?
3. Multi-agent — when does it actually pay off?
4. What's the failure mode of multi-agent nobody mentions?
5. How do you stop any of these looping forever?
6. Where does the control flow live — the prompt or the code?
7. When is the answer "don't use an agent"?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
