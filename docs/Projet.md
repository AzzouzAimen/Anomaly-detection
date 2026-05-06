Project Advanced Database Systems & Big Data Mining
Medical Time-Series Dataset Curation
Explainable Anomaly Detection: From Raw Signals to Validated Benchmarks

1. Project Overview
Medical time-series data, including electrocardiographic recordings, electroencephalographic signals, respiratory measurements, and thermal sensor readings, is central to non-invasive diagnosis, continuous patient monitoring, and early anomaly detection. Large volumes of physiological data are available through public repositories such as PhysioNet and the UCI Machine Learning Repository; however, this information is fragmented across heterogeneous formats, inconsistent annotation conventions, and varying sampling standards.
As a result, physiological time-series data is difficult to aggregate, preprocess, benchmark, or reuse at scale. Variability in signal quality, missing annotations, class imbalance, and inconsistent labeling strategies limit the potential value of these recordings for systematic machine learning research and clinical AI validation.
Addressing these challenges requires a structured approach to data acquisition, preprocessing, cleaning, validation, and documentation, with particular attention to signal integrity, ground truth traceability, and scientific reproducibility. A well-designed medical time-series benchmark can transform scattered raw recordings into a coherent, reusable research resource capable of supporting rigorous evaluation of explainable AI methods.
2. Project Requirements
The project aims to design, curate, and validate a Medical Time-Series Benchmark Dataset that satisfies the following requirements. The dataset must be built from publicly available and ethically reusable physiological recordings. All signals collected or generated must pertain to one of the six designated medical topics. Each signal must be represented using a consistent and well-defined structure enabling cross-subject and cross-session comparison. Raw data must be preserved to ensure traceability and reproducibility. Data must undergo systematic cleaning and validation to address noise, missing values, label inconsistencies, and class imbalance. The final dataset must be stored in an organized and persistent format that supports model training, evaluation, and reuse. The repository must include clear documentation describing signal properties, preprocessing decisions, labeling conventions, known limitations, and ethical considerations. The resulting benchmark must be suitable for training and evaluating an attention-based anomaly detection framework.
3. Expected Impact
By addressing these requirements, the project highlights the real-world challenges of managing physiological signal data and demonstrates how rigorous preprocessing and documentation can significantly improve the scientific value and reproducibility of medical AI benchmarks. The resulting datasets serve as foundations for explainable anomaly detection research, contribute to Algeria's open research data infrastructure, and provide students with end-to-end experience in biomedical data science.
4. Project Organization and Evaluation
The project is organized into three progressive sprints, each addressing a key phase in the data curation lifecycle. Each sprint produces mandatory technical outputs that are validated and graded before progression to the next phase. Progression between sprints is conditional upon successful validation of the previous sprint. The final evaluation is based primarily on the quality, consistency, reproducibility, and documentation of the dataset produced across all sprints.

Sprint 1 — Data Ingestion & Architectural Modeling
Goal:
Acquire raw physiological data and design a dual-database architecture to compare traditional RDBMS (PostgreSQL) against Time-Series optimized storage.
Key Activities:
Data Acquisition: Identify and download the assigned public dataset. Ensure raw signal integrity is maintained.
Schema Design (The "Relational" View): Design a Normalized Relational Schema for PostgreSQL. This must include tables for Subjects, Recordings, and a signals table with proper foreign keys.
Schema Design (The "Time-Series" View): Propose a schema optimized for a Time-Series Database. Focus on how to handle high-frequency timestamps and sensor metadata.
Ingestion Strategy: Define the ETL logic. How will raw data be parsed and prepared for parallel insertion into both database types?
Benchmarking Protocol: Define the specific SQL queries (e.g., range scans, aggregations) that will be used in Sprint 2 to test the performance limit of each system.
Expected Technical Outputs:
Raw Data Repository: A local landing zone containing the unprocessed recordings and their original metadata.
ER Diagram (ERD): A formal diagram showing the Relational structure in PostgreSQL.
Architecture Document: A brief report (2-3 pages) justifying:
The choice of the secondary Time-Series Database.
How the schema addresses the "Time-Series specific" challenges (e.g., indexing on time).


Baseline Metadata File: A JSON or CSV file documenting the source, sampling rates, and licenses for all subjects.

Sprint 2 — Data Wrangling & Performance Benchmarking
Goal:
Implement the ETL pipeline, transform raw signals into structured data, and conduct a comparative performance analysis between the two database architectures.
Key Activities:
ETL Implementation: Develop a reproducible pipeline to clean, normalize, and segment raw signals.
Dual Ingestion: Load the processed data into both the PostgreSQL (Standard) and Time-Series (Optimized) databases.
Stress Testing: Execute a series of standardized "Read/Write" tests.
Write: Measure ingestion time for the entire dataset (rows/sec).
Read: Measure latency for range queries (e.g., "Retrieve 1 hour of ECG for Subject 01").
Aggregation: Measure time for downsampling (e.g., "Calculate the Mean Heart Rate per minute").


Storage Analysis: Measure the physical disk space (on-disk size) consumed by both systems after indexing.
Expected Technical Outputs:
The Comparative Benchmark Report: A table and series of charts comparing Ingestion Rate, Query Latency, and Compression Ratios.
The Structured Repository: Access credentials or export files for the two databases containing the cleaned/windowed data.
Cleaning & Transformation Log: Documentation of all signal processing decisions (handling missing values, resampling).
Python ETL Pipeline: Reproducible code covering the transformation and the database connectors (e.g., psycopg2 for Postgres vs. influxdb-client).

Sprint 3 — Model Integration & Final Validation
Goal:
Utilize the optimized database to train the Anomaly Detection model and finalize the dataset documentation for public research.
Key Activities:
Database-to-Model Pipeline: Connect the framework to the optimized database. Evaluate the speed of data fetching during the training loop compared to loading from raw files.
Model Evaluation: Train and validate the attention-based model using the metrics (F1-score, AUC-ROC, etc.) defined in the common protocol.
Explainability Analysis: Use the database to store and query "Attention Maps"—identifying exactly which time segments the model flagged as anomalous.
Robustness Testing: Inject synthetic noise/distortions and observe how the database integrity and model performance hold up.
Final Publication: Package the "Winner" database schema and the resulting benchmark dataset for the laboratory repository.
Expected Technical Outputs:
Model Evaluation Report: Performance metrics (Precision, Recall, MAE) and attention visualizations (heatmaps).
Final Data Documentation Card: A professional "README" covering the database schema, query examples, signal properties, and ethical considerations.
Published SQL/Schema Files: DDL scripts and a sample data dump ready for external researchers to replicate the environment.
The "Architectural Verdict": A final summary concluding which database system (Standard vs. Time-Series) is superior for medical monitoring at scale.

5. Research Topics
Each team of nine students is assigned one of the following six medical time-series topics. Topic assignments are fixed and must be maintained consistently across all three sprints.
Topic M1: ECG ST-T Analysis uses the PhysioNet European ST-T Database, comprising 90 annotated two-channel ambulatory ECG recordings from 79 subjects, with over 768 labeled episodes of ST segment and T-wave chang
Topic M2: EEG Epilepsy Detection uses the PhysioNet CHB-MIT Scalp EEG Database covering 24 pediatric patients across 23 channels sampled at 256 Hz with 182 annotated seizure events.
Topic M3: Sleep Stage Anomaly Detection uses the PhysioNet Sleep-EDF Database covering 153 subjects recorded across EEG and EOG channels with more than 20 hours per subject.
Topic M4: Respiratory Apnea Detection uses the PhysioNet Apnea-ECG Database containing 70 recordings of approximately 8 hours each with synchronized ECG and respiratory signals.
Topic M5: Human Activity Anomaly Detection uses the UCI Human Activity Recognition Dataset covering 30 subjects, 561 features derived from accelerometer and gyroscope signals, across 6 activity classes and 10,299 windows.
Topic M6: Synthetic Thermal Time-Series Generation focuses entirely on the design and generation of a synthetic dataset simulating skin temperature readings from a wearable breast thermal monitoring device.


