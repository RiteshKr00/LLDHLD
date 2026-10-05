# Topic 5: hallucination control — layered defence

## The prompt

> "You said you have a two-layer hallucination defence: a deterministic validator, then a
> maker-checker LLM pass. Why in that order? And what does the second layer catch that the
> first can't?"

## The follow-up bank

1. Why deterministic before the LLM check, not the other way round?
2. What does the maker-checker catch that code can't?
3. How do you stop the checker rubber-stamping?
4. Structured output — schema in the prompt, or provider-enforced?
5. Have you measured the catch rate of either layer?
6. Isn't this just two chances to be wrong?
7. What's the difference between grounding and validation?
