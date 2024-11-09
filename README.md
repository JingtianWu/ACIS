# SKY - Autonomous Code Implementation System

This project automates the incremental implementation of unimplemented functions in Python libraries using a test-driven approach.

## Files

### 1. `extract_tests.py`
Extracts all test cases from the `tests` folder of a given library. It identifies test classes and functions, classifies them, and displays the extracted tests for further processing.

### 2. `identify_files_to_implement.py`
Scans the library source files to identify functions marked as unimplemented (e.g., containing `pass` or `NotImplementedError`). It lists these functions for incremental implementation.

### 3. `main.py`
Coordinates the workflow:
- Extracts test cases using `extract_tests.py`.
- Identifies unimplemented functions using `identify_files_to_implement.py`.
- Implements functions incrementally (simulated without LLM integration).
- Runs relevant test cases and retries up to three times if tests fail.
- Executes all tests at the end to evaluate overall performance.

## Usage
Run the main script:
```bash
python main.py
```

The system processes the target library incrementally and adapts based on test outcomes, facilitating a structured, test-driven code implementation process.
