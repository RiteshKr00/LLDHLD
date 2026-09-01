# Chess — HLD (quick): online multiplayer platform

Companion to [`solution.py`](solution.py) (the single-game engine).
General machinery → `../HLD-revision.md` (flow) · `../HLD-method-bank.md` (menu) · `../HLD-reference.md` (depth).

> **Framing:** the LLD is the *rules engine* for one game. The HLD is everything around it —
> matchmaking, real-time move delivery, and persisting millions of concurrent games.
> **The engine itself doesn't change; it just runs server-side instead of in one process.**

## 1. Scope
- **Functional:** find an opponent (matchmaking by rating), play moves in real time, spectate, reconnect after a drop, game history, clocks.
- **Non-functional:** **low latency** (a move must reach the opponent in <100ms — it's a live game) · **never trust the client** · durable game state (a disconnect must not lose the game).

## 2. Estimate
- 1M DAU, ~5 concurrent games per 100 users → **~50K concurrent games** = 100K connected players.
- A move every ~5s per game → **~10K moves/sec**. Small compute, but each move must be **pushed** to another human immediately.
- Storage: 10M games/day × ~1KB of move history ≈ **10 GB/day** → cheap, archivable.

## 3. Architecture
```
Players ──WebSocket──▶ Gateway (sticky, holds the live connection)
                          │
                          ▼
                    Game Service  ──▶ runs solution.py's ChessOrchestrator
                          │              (validation is SERVER-side, always)
              ┌───────────┼────────────┐
              ▼           ▼            ▼
        Redis          Postgres     Kafka
   (live game state,  (finished    (move events →
    presence, locks)   games,        history/analytics)
                       ratings)
```
- **WebSocket, not REST** — the server must *push* the opponent's move; polling adds latency and wastes connections. Sticky routing so both players of a game land on the same Game Service instance (or the state lives in Redis so any instance can serve).
- **Live game state in Redis** (board position, whose turn, clocks) — read/written on every move, must be fast. **Postgres** stores finished games + ratings (durable, queryable).

## 4. Key decisions
- **Never trust the client.** The browser may render a board, but **every move is re-validated server-side** by the same `make_move` you wrote. A hacked client sending an illegal move gets rejected — this is why the rules engine lives on the server, not just in the UI.
- **Turn-based = the LLD's no-concurrency assumption still holds.** Only one player can legally move at a time, and the server enforces turn order — so there's no move-level race. The concurrency that *does* exist is at the **matchmaking** layer (two requests grabbing the same opponent) → that's the familiar atomic-claim/TOCTOU problem again, solved the same way (Redis atomic op).
- **Matchmaking:** a rating-bucketed queue in Redis; pop two nearby-rated players atomically, create a game. Widen the rating window the longer someone waits.
- **Clocks are server-authoritative** — the client displays time, the server owns it, or players cheat by stalling.
- **Reconnect:** because live state is in Redis (not in the WebSocket connection's memory), a dropped player reconnects and resumes — the state was never tied to the socket.

## 5. Scale & failure
- **Bottleneck:** concurrent WebSocket connections (memory/FD per connection), not CPU — chess validation is trivially cheap. Scale by adding stateless gateway nodes.
- **Game Service dies** → its games' state is in Redis, so another instance picks them up; players reconnect.
- **Redis down** → live games stall (state is unreachable); mitigate with Redis Cluster + replicas. Finished games in Postgres are unaffected.
- **At 10×:** more gateway/game nodes, Redis Cluster sharded by `game_id`, regional deployment for latency (chess is latency-sensitive; a cross-continent RTT is felt).

## LLD ↔ HLD mapping
| LLD (`solution.py`) | HLD (this doc) |
|---|---|
| `ChessOrchestrator.make_move` | runs **server-side** on every move — the anti-cheat boundary |
| `Match` (board, turn, status) | serialized into **Redis** as live game state |
| `is_move_safe` / rules engine | unchanged — same code, just hosted |
| in-memory `Board` | Redis for live games → Postgres once finished |
| single game, one process | 50K concurrent games across a stateless fleet |
| *(no concurrency — turn-based)* | race moves to **matchmaking** (atomic claim on the queue) |
