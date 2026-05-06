### Design Decisions for PostgreSQL Database

**1. Normalization: Subject → Recording → Signal Hierarchy**

*Decision:*  
We separated `subjects`, `recordings`, `signals`, `annotations_apnea`, and `annotations_qrs` into different tables.

*Justification:*  
This follows a normalized relational structure and avoids mixing metadata, high-frequency signals, and annotations in the same table. Most records are treated as one subject per recording, but the dataset documentation notes that `c05` and `c06` originate from the same original recording. By keeping a separate `subjects` table, both recordings can be linked to the same subject when needed.

---

**2. Handling Frequency Mismatch: Signals and Annotations are Separate**

*Decision:*  
We created separate tables for high-frequency signal samples and low-frequency annotations:

- `signals`: ECG and optional respiratory/SpO2 values sampled at 100 Hz.
- `annotations_apnea`: expert apnea labels, with one label per minute.
- `annotations_qrs`: machine-generated heartbeat locations.

*Justification:*  
The ECG signal contains 100 samples per second, which means 6,000 samples per minute. Apnea annotations are only available once per minute. If we stored the apnea label directly inside every signal row, the same label would be duplicated 6,000 times per minute. This would waste storage, violate clean relational design, and make label updates inefficient.

---

**3. Handling Sparse Modalities: Wide Signal Table with NULLs**

*Decision:*  
We used a single wide `signals` table containing columns for ECG, respiration, and SpO2:

- `ecg_value`
- `resp_c`
- `resp_a`
- `resp_n`
- `spo2`

For ECG-only records, the respiratory and SpO2 columns are set to `NULL`.

*Justification:*  
All records contain ECG, but only 8 records contain the additional respiratory and oxygen saturation signals. Using nullable columns keeps the schema simple and consistent across all recordings. This also supports later machine learning preprocessing, where missing modalities can be padded, masked, or ignored without changing the database structure.

---

**4. Artificial Timestamps and Sample Indexing**

*Decision:*  
We introduced an artificial `recording_start_time`, set by default to:

`2000-01-01 00:00:00`

Each signal row also stores a `sample_index`.

*Justification:*  
The PhysioNet Apnea-ECG dataset does not provide real calendar timestamps. It represents time using elapsed samples. To support SQL time-range queries and TimescaleDB hypertables, we synthesize timestamps using:

`recorded_at = recording_start_time + sample_index / sampling_rate_hz`

The `sample_index` is preserved to maintain traceability to the original raw WFDB files.

---

**5. Data Types, Keys, and Indexing**

*Decision:*  
Instead of using a surrogate `BIGSERIAL` key in the `signals` table, we use a composite primary key:

`PRIMARY KEY (recording_id, sample_index)`

We also add a unique constraint on:

`UNIQUE (recording_id, recorded_at)`

*Justification:*  
The natural identity of a signal sample is the recording it belongs to and its position inside that recording. Therefore, `(recording_id, sample_index)` is more meaningful than an auto-incrementing ID. The unique constraint on `(recording_id, recorded_at)` prevents duplicate timestamps and supports efficient time-range queries.

Additional indexes are added to support Sprint 2 benchmark queries, such as retrieving one hour of ECG data, filtering apnea events, and aggregating QRS annotations.