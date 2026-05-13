# Sprint 2 Benchmark Report

## Scope

Records benchmarked: a01
Benchmark method: persistent_psycopg2_connection
Warmup iterations per query: 2

## Query Latency

| Test | PostgreSQL avg (ms) | TimescaleDB avg (ms) | PostgreSQL p95 (ms) | TimescaleDB p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| qrs_aggregation | 0.28 | 0.51 | 0.32 | 0.55 |
| range_query_latency | 1.87 | 2.28 | 1.96 | 2.36 |
| signal_label_join | 1.02 | 1.37 | 1.02 | 1.39 |
| temporal_aggregation | 0.80 | 0.91 | 0.83 | 0.95 |

## Write Throughput

PostgreSQL total throughput: 19722.80262532252
TimescaleDB total throughput: 12308.299226628296

## Storage

PostgreSQL total size: 448.00 KB
TimescaleDB total size: 80.00 KB
TimescaleDB pre-compression total size: 80.00 KB
TimescaleDB compression ratio: 1.0

## Generated Artifacts

- Latency CSV: benchmarks/oracle_smoke_report/latency_summary.csv
- Storage CSV: benchmarks/oracle_smoke_report/storage_summary.csv
- Throughput CSV: benchmarks/oracle_smoke_report/throughput_summary.csv
- Charts: throughput_comparison.png, latency_comparison.png, storage_comparison.png, compression_comparison.png