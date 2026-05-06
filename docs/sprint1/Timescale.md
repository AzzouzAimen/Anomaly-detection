### Key Differences from the PostgreSQL Version

1. **No Surrogate `BIGSERIAL` ID on the `signals` Table**

In the PostgreSQL schema, we already avoid using a surrogate `BIGSERIAL` ID and instead rely on meaningful composite keys. In the TimescaleDB schema, this becomes even more important because hypertables require unique constraints and primary keys to include the time partition column.

For the `signals` hypertable, the primary key is:

`PRIMARY KEY (recording_id, recorded_at)`

This means each signal sample is uniquely identified by its recording and timestamp.

---

2. **Hypertable Conversion**

The main difference is that TimescaleDB converts the high-frequency tables into hypertables using:

`create_hypertable(...)`

The `signals` table is partitioned by `recorded_at`, allowing TimescaleDB to split the large signal table into smaller time-based chunks. This is useful for range queries, downsampling, and time-window analysis.

The following tables are modeled as hypertables:

- `signals`
- `annotations_apnea`
- `annotations_qrs`

---

3. **Chunking for Time-Series Queries**

In standard PostgreSQL, all signal rows are stored in one large relational table. Indexes help, but queries over hundreds of millions of rows can still become expensive.

TimescaleDB stores the same logical table as multiple time-based chunks. When a query requests a specific time range, TimescaleDB can skip irrelevant chunks and scan only the chunks needed for that time interval.

This is especially useful for benchmark queries such as:

- retrieving one hour of ECG data,
- calculating one-minute ECG averages,
- computing heartbeats per minute from QRS annotations.

---

4. **Compression Configuration**

TimescaleDB supports native compression for hypertables. In our schema, compression is configured on the `signals` table using `recording_id` as the segment key and `recorded_at` as the ordering key.

This is suitable because most project queries filter by `recording_id` and then scan a time range.

Compression will be measured during Sprint 2 by comparing table size before and after compression.

### Why TimescaleDB is Suitable for Topic M4

**1. Time-Based Chunking**

The Apnea-ECG dataset contains long recordings sampled at 100 Hz. This produces a very large number of signal rows. TimescaleDB hypertables split this data into time-based chunks, making time-range queries more efficient than scanning one very large table.

---

**2. Efficient Range Queries**

Medical monitoring workloads often request a specific time interval, such as one hour of ECG for one patient. TimescaleDB is optimized for this type of query because it can use chunk exclusion to skip irrelevant time partitions.

---

**3. Native Downsampling Functions**

TimescaleDB provides time-series functions such as `time_bucket()`, which are useful for converting high-frequency ECG samples into lower-frequency features. For example, ECG values can be aggregated into one-minute averages for machine learning preprocessing.

---

**4. Compression Support**

The high-frequency `signals` table is expected to consume significant disk space. TimescaleDB compression can reduce storage usage by grouping similar values and ordering data efficiently. The actual compression ratio will be measured during Sprint 2.

---

**5. Fair Comparison with PostgreSQL**

Both PostgreSQL and TimescaleDB use the same logical schema and contain the same transformed data. This makes the Sprint 2 benchmark fair because the comparison focuses on the database architecture rather than differences in data preparation.