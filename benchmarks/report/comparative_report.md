# Sprint 2 Benchmark Report

## Scope

Records benchmarked: a01, a05, b01
Benchmark method: persistent_psycopg2_connection
Warmup iterations per query: 2

## Query Latency

| Test | PostgreSQL avg (ms) | TimescaleDB avg (ms) | PostgreSQL p95 (ms) | TimescaleDB p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| qrs_aggregation | 10.55 | 6.13 | 11.92 | 6.75 |
| range_query_latency | 758.79 | 530.38 | 1102.92 | 534.41 |
| signal_label_join | 66274.55 | 83151.84 | 69943.32 | 93113.41 |
| temporal_aggregation | 5898.16 | 246.46 | 5893.11 | 250.47 |

## Write Throughput

PostgreSQL total throughput: 27068.06608111547
TimescaleDB total throughput: 15365.842946148765

## Storage

PostgreSQL total size: 26.72 GB
TimescaleDB total size: 80.00 KB
TimescaleDB pre-compression total size: 80.00 KB
TimescaleDB compression ratio: 1.0

## Generated Artifacts

- Latency CSV: benchmarks/report/latency_summary.csv
- Storage CSV: benchmarks/report/storage_summary.csv
- Throughput CSV: benchmarks/report/throughput_summary.csv
- Charts: throughput_comparison.png, latency_comparison.png, storage_comparison.png, compression_comparison.png