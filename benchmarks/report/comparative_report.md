# Sprint 2 Benchmark Report

## Scope

Records benchmarked: a01, a05, b01
Benchmark method: persistent_psycopg2_connection
Warmup iterations per query: 2

## Query Latency

| Test | PostgreSQL avg (ms) | TimescaleDB avg (ms) | PostgreSQL p95 (ms) | TimescaleDB p95 (ms) |
| --- | ---: | ---: | ---: | ---: |
| qrs_aggregation | 10.42 | 6.14 | 11.77 | 6.79 |
| range_query_latency | 757.59 | 533.97 | 1104.51 | 538.49 |
| signal_label_join | 66416.07 | 86098.03 | 69774.51 | 96204.63 |
| temporal_aggregation | 5764.69 | 247.77 | 5793.56 | 253.43 |

## Write Throughput

PostgreSQL total throughput: 27068.06608111547
TimescaleDB total throughput: 15365.842946148765

## Storage

PostgreSQL total size: 26.72 GB
TimescaleDB total size: 3.38 GB
TimescaleDB pre-compression total size: 3.38 GB
TimescaleDB compression ratio: 1.0

## Generated Artifacts

- Latency CSV: benchmarks/report/latency_summary.csv
- Storage CSV: benchmarks/report/storage_summary.csv
- Throughput CSV: benchmarks/report/throughput_summary.csv
- Charts: throughput_comparison.png, latency_comparison.png, storage_comparison.png, compression_comparison.png