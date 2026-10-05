# Topic 9: migrations, and the populated-table hazard

## The prompt
> "You authored 37+ Django migrations with custom `RunPython` helpers. Tell me how you'd add
> a NOT NULL column to a table with a million rows — and what your current schema management
> gets wrong."

## The follow-up bank
1. What's `RunPython` for, and what can go wrong with it at scale?
2. How do you add a NOT NULL column to a populated table?
3. Why doesn't `SET DEFAULT` solve it?
4. How would you introduce migrations to a legacy database?
5. Why write `downgrade()` if you'll never run it?
6. What can autogenerate NOT detect?
7. Your test DB starts empty. What does that hide?
