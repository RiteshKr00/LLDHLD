# Topic 14: agent memory, context and runtime

## The prompt

> "Your agent works in a demo. What do you have to build before it can run in production?"

## Clarifying questions worth asking back

1. "Single-turn tasks or long conversations?" — decides whether memory is even in scope.
2. "Do tools have side effects?" — decides whether idempotency is mandatory.
3. "Who sees a failure — a user, or a queue?" — decides the degradation design.

## The follow-up bank

1. Context window fills up mid-run. What happens?
2. How do you stop cost growing quadratically with conversation length?
3. What's "context engineering" and why does it matter more than prompt engineering?
4. A tool call succeeded but the run crashed before recording it. Now what?
5. How do you debug a run that went wrong three steps ago?
6. How do you handle a right-to-erasure request against agent memory?
7. What do you alert on?

Answers: `explained.md` · runnable: `solution.py` · platform view: `hld.md`
