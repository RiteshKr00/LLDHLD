# Design scenario 27: support copilot with escalation

## The prompt

> "Deflect support tickets with an AI agent. Don't make customers angrier."

*The second sentence is the actual brief. Deflection rate is trivially optimisable and
optimising it is how you ship something that looks successful on the dashboard and is hated.*

---

## Clarifying questions to ask FIRST

1. **What is the current deflection rate and CSAT baseline?** *(Without both, you cannot tell
   an improvement from a trade. And you will be trading.)*
2. **Can the agent take actions, or only answer?** *(Refunds and cancellations are a
   different product with a different risk profile. Answering is reversible; acting is not.)*
3. **Is there an SLA on human handoff?** *(Decides whether escalation is a queue or a
   promise, and whether "escalate on low confidence" is affordable.)*
4. **What does a wrong answer cost this business?** *(A wrong shipping estimate is an
   apology. A wrong cancellation-policy answer is a chargeback.)*
5. **Is the knowledge base actually correct and current?** *(A deflection engine on a stale
   KB industrialises the wrong answer. Frequently the real problem.)*
6. **Who owns CSAT for AI-handled tickets?** *(If nobody does, deflection wins every
   argument by default.)*

---

## The follow-up bank

1. You deflect 40% of tickets. Why might that be a bad outcome?
2. What is your escalation trigger, and what happens at the boundary?
3. A customer wants a human immediately. What does your system do?
4. What does the human receive when a ticket escalates?
5. The agent can issue refunds. Design that.
6. Which metrics would you refuse to report on their own?
7. Your KB article is wrong. What happens, and how do you find out?
8. How do escalated tickets make the system better?
9. CSAT drops two points while deflection rises ten. What do you do?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
