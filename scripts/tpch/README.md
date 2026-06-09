
## TPCH Setup Helper
---

### Directory Structure

```
tpch
├─ setup_tpch.py
├─ setup_utils
│   ├─ generate_tpch_schema.py
│   ├─ generate_tpch_data_dbgen.py
│   ├─ load_tpch.py
│   └─ create_index.py
├─ utils
│   ├─ analyze.py
│   ├─ build_reports.py
│   ├─ comparator.py
│   ├─ query_registry.py
│   ├─ sweep.py
│   └─ run.py
├─ queries
│   ├─ qt1.sql
│   ├─ ...
│   └─ qt21.sql
├─ results
│   ├─ qt1
│   │  ├─ analysis_report.txt
│   │  ├─ analysis_results.json
│   │  ├─ phases.json
│   │  ├─ plan_diagram.json
│   │  ├─ sweep_report.txt
│   │  ├─ sweep_results.json
│   │  └─ switches.json
│   ├─ ...
│   └─ qt21
└─ README.md
```
---

### Configurations for TPCH setup in required device

Enter suitable values into these variables:

- Enter Custom Name for TPCH DB in your system with `$name` (mandatory)
- Choose Scale Factor (SF) using `$SF` (mandatory)

---

### Run TPCH Setup

Run TPCH Setup by running this script:
BASE_DIRECTORY$ `python tpch/setup_tpch.py`

---