# Topic 10: cost attribution across providers

## The prompt
> "You built per-call cost metering across five providers where the authoritative number
> arrives late by webhook. Walk me through the reconciliation — and then tell me how you'd
> turn visibility into control."

## The follow-up bank
1. Webhooks are unreliable. What if it never arrives?
2. The webhook fires twice. Now what?
3. How do you verify the webhook is really from the provider?
4. Why does "displayed rate = billed rate" matter enough to design around?
5. How would you turn this into cost control?
6. Why is a constant-time comparison needed for a secret?
7. Why fail closed if the secret is unset?
