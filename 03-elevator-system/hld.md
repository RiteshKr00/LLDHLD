# Elevator — HLD (quick)

> **Framing (say this first):** one building's controller is a **real-time embedded** system — the dispatch loop
> stays **on the edge** (latency + safety; you can't round-trip to the cloud to close a door). The HLD-worthy
> problem is a **fleet platform**: monitor + optimize thousands of elevators across buildings.

## 1. Scope
- **Functional:** ingest telemetry (floor, state, load, faults) per car; live monitoring dashboard; remote commands (lock/unlock, priority dispatch) with ack; fault alerts; predictive maintenance.
- **Non-functional:** massive write ingest, near-real-time, highly available, durable history. **Safety is NOT ours** — it's edge/hardware (fail-safe brakes); backend-down = lose monitoring, not safety.

## 2. Estimate (the crux is write volume)
- 1M elevators × 1 telemetry msg/sec = **~1M writes/sec** → this is a **write-heavy, time-series** problem (opposite of the read-heavy parking platform).
- History: 1M/s × 86,400 ≈ 86B points/day → downsample + tier.

## 3. Architecture
```
Elevators (edge: real-time dispatch stays LOCAL)
   │  MQTT / gateway
   ▼
Kafka (ingest buffer, absorbs spikes)
   ├─▶ stream processor (Flink) ─▶ Time-Series DB (Timescale/Influx/Cassandra)   [monitoring]
   ├─▶ fault-detection stream ───▶ Alerting                                       [notify on-call/tech]
   └─▶ cold storage (S3/parquet) ─▶ ML predictive-maintenance                     [offline]

Command path: Dashboard ─▶ Command Svc ─▶ MQTT down to car (with ack)
```

## 4. Key decisions (the interview signal)
- **Edge vs cloud:** real-time car control = **edge** (safety + latency); cloud = telemetry, analytics, optimization hints. This split is the whole answer.
- **Ingest:** **Kafka** absorbs the 1M/s spikes; partition by `building_id`/`elevator_id`.
- **Storage:** **time-series DB** (not a relational primary) — append-heavy, time-indexed; hot recent + rolled-up/downsampled history in cold storage.
- **Alerting:** **stream processing** detects fault patterns in-flight → page a technician.
- **Reliability:** at-least-once ingest (Kafka + idempotent consumers); backend outage degrades monitoring only, never car safety.

## 5. Bottleneck & scale
- Bottleneck = the **1M/s write ingest** → Kafka partitioning + time-series sharding by elevator/building; downsample old data.
- Contrast worth stating: **parking platform was read-heavy (cache + geo); elevator fleet is write-heavy (Kafka + time-series).** Same method, opposite shape.

## LLD ↔ HLD
| LLD (one building) | HLD (fleet) |
|---|---|
| `ElevatorSystem.step()` dispatch loop | stays **on the edge**, real-time |
| `Elevator` state (Idle/Moving/…) | telemetry stream into the time-series DB |
| in-memory car objects | 1M cars emitting → Kafka → TSDB |
| — | cloud adds monitoring, alerting, predictive maintenance |
