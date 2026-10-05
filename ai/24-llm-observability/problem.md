# Design scenario 10: LLM observability platform

## The prompt

> "We have four LLM features in production and no idea what any of them are doing. Build the
> observability. Budget matters."

*The second sentence is the whole question. Anyone can say "log everything". The answer is what
you keep, at what rate, and cut by what.*

---

## Clarifying questions to ask FIRST

1. **Debugging individual requests, or tracking aggregate quality?** *(Two different stores. One
   wants whole traces and a search box over 30 days; the other wants cheap aggregates over a
   year. Building one thing for both gets you an expensive store you cannot afford to keep.)*
2. **Can we store prompt and response content at all, given the tenant contracts?** *(Decides
   whether a payload store exists, or whether you keep hashes and lengths and nothing else.)*
3. **Do we own the call sites, or are teams calling providers directly?** *(A gateway means
   instrumentation is one library and coverage is 100%. An SDK you have to evangelise never
   reaches 100%, and partial coverage is worse than none — the gap is where the incident is.)*
4. **Retention: same for cost data and content?** *(It should not be. Cost needs 400 days for
   year-on-year; content should not survive 30.)*
5. **Is there tracing already, and on what standard?** *(With OpenTelemetry in place you are
   extending a span schema. Without it you are building context propagation first, and that is
   the longer job.)*
6. **Who is paged for a quality regression, and what do they do at 2am?** *(An alert nobody can
   act on gets silenced within a week, and then you have neither the alert nor the trust.)*

---

## The follow-up bank

1. 600k calls/day, full prompt and response. What is that a year, and what do you do about it?
2. You sample 2% to control that. How is the error analysis still usable?
3. Your metrics backend has 2.5M active series. Where did they come from, and how do you get
   them down without losing per-tenant visibility?
4. Latency is flat, error rate is flat, and the answers got worse on Tuesday. Find it.
5. A tenant invokes their right to erasure. What does that mean for the trace store?
6. The collector is down for ten minutes. What happens to the application?
7. What is the difference between a refusal and an error, and who owns each?
8. How do you know the quality sample is representative?
9. What is the smallest quality regression you can detect, and what sets that number?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
