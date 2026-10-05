# Design scenario 22: document extraction with an accuracy SLA

## The prompt

> "Extract 20 fields from 50k invoices a month, contractually 99% field-level accuracy."

*There is a number hidden in that sentence, and finding it is the whole test. 20 fields at 99%
each is 0.99²⁰ — **82% of documents perfect**. Say that in the first thirty seconds and the
conversation changes shape.*

---

## Clarifying questions to ask FIRST

1. **Is 99% per field or per document?** *(The single most important question here. 20 fields
   at 99% each gives 82% document-perfect. To reach 99% per document you need 99.95% per
   field, which no model does unaided.)*
2. **Is human review budgeted?** *(Given the arithmetic above, human-in-the-loop is not a
   fallback — it is the architecture. If there is no review budget, the SLA is not
   achievable and someone needs to hear that now.)*
3. **Templated or arbitrary documents?** *(Recurring senders mean cached layouts and a much
   cheaper path for most of the volume.)*
4. **What does an error cost downstream?** *(A wrong postcode is a re-send. A wrong bank
   account is fraud. Fields are not equally important and the SLA usually pretends they
   are.)*
5. **Which fields are actually hard?** *(Accuracy varies enormously by field. A single
   aggregate number hides the one field that is broken.)*
6. **Who signs off that a document is correct, and what is the reviewer's own error rate?**
   *(Reviewers are not oracles. If nobody has measured this, the SLA has no floor.)*

---

## The follow-up bank

1. The contract says 99%. What do you ask before agreeing to it?
2. How many documents need human review, and how do you decide which?
3. A reviewer sees an uncertain field. Do they re-check the other nineteen?
4. Which fields would you never trust a model on?
5. Your aggregate accuracy is 99.2% and a customer is furious. Explain.
6. How do you get cheaper over time without getting worse?
7. What stops the eval set going stale?
8. Confidence is 0.97 and the field is wrong. What went wrong with confidence?
9. Reviewer throughput becomes the bottleneck. What do you do?

Answers: `explained.md` · runnable: `solution.py` · scaling: `hld.md`
