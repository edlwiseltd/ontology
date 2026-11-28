# Document-to-ontology spike: evidence

Synthetic documents and engineer-written labels (`cases/`), and what the benchmark produced (`results/`). No
customer data, no credential, no provider output.

| File | What |
|---|---|
| `cases/*.txt` | Four synthetic documents (three for tuning, `clinic-bookings` held out) |
| `cases/*.labels.json` | Reference labels written with each document; not an expert's judgment |
| `results/first-run-before-fixes.json` | The extractor's very first output on the three tuning documents, kept as it came out |
| `results/benchmark.json`, `.txt` | `python deploy/make_docintel_benchmark.py`, compared with a fresh run by a test |

Protocol: `planning/AUTOLOGY_NER_ONTOLOGY_EXTRACTION_EVALUATION_PROTOCOL.md`.
