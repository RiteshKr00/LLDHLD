# Design scenario 31: incident — cost spiked 5x overnight

## The prompt

> "Yesterday you spent five times normal on LLM calls. Nothing was deployed. Find it and design
> what should have caught it."

*"Nothing was deployed" is the interesting clause. It rules out the first thing everyone
reaches for and forces you to know the causes that need no code change — which is most of them.*

---

## Clarifying questions to ask FIRST — out loud, as triage

1. **Is it volume or cost per call?** *(Divide spend by call count. This one division splits
   the whole problem in two and takes thirty seconds.)*
2. **Which tenant, feature and model?** *(A spike is almost never uniform. If it is, suspect
   a provider price change or a routing shift.)*
3. **When exactly did it start?** *(Sharp edge or a ramp? A sharp edge is a config or
   routing change; a ramp is a loop or a growing retry storm.)*
4. **Did anything change that is not a deploy?** *(A prompt edit, a flag, a re-index, a
   provider incident, a backfill someone kicked off. "Nothing was deployed" is true and
   irrelevant.)*
5. **What is the cache hit rate, now versus last week?** *(A collapse silently multiplies
   cost and shows up as a volume increase at the provider.)*
6. **Is it still happening?** *(Decides whether you are stopping a fire or doing forensics.)*

---

## The follow-up bank

1. What is the very first number you look at, and why that one?
2. Volume is flat and cost per call doubled. What are your candidates?
3. Nothing was deployed. How can cost change?
4. How would a cache invalidation show up on your dashboards?
5. An agent has no step budget. What does the bill look like?
6. What is the immediate mitigation, before you know the cause?
7. What should have caught this on the day?
8. Why is alerting on absolute spend the wrong design?
9. How do you stop this being a monthly-invoice discovery?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
