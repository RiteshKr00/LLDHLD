# Topic 12: LangChain & LangGraph — the framework crash course

## The prompt

> "You list LangGraph on your resume. Explain what it gives you that plain Python doesn't —
> and when you'd choose not to use it."

## Why this topic exists

LangChain and LangGraph appear on your resume and in your PII filter. They're also the two
things most candidates use without being able to explain, so an interviewer probing them is
probing whether you understand *orchestration*, not whether you've read the docs.

---

## Clarifying questions worth asking back

1. "Do you want the LangChain primitives or the LangGraph execution model?" — different answers.
2. "Are we talking about a fixed pipeline or a loop the model controls?" — that's the whole choose-or-not question.

---

## The follow-up bank

1. What does `init_chat_model` actually buy you over calling a provider SDK?
2. Why typed `Message` objects instead of dicts?
3. What is a LangGraph `State`, and what is a reducer?
4. `add_messages` — what does it do and why can't you just use a list?
5. When is a `StateGraph` overkill?
6. What is a checkpointer for?
7. `Send` / fan-out — when do you need it?
8. LangChain vs LangGraph vs LCEL vs an agent framework — what's the actual distinction?
9. How do you test a graph without calling a model?
10. Your PII filter is a 5-node graph. Why a graph and not five function calls?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
