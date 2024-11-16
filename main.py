# main.py

import sys
import subprocess
from pathlib import Path
from collections import defaultdict
from typing import Dict, List
import re
import os  # Import os for environment variables

# Import functions from your existing scripts
from extract_tests import (
    is_library_dir,
    find_libraries,
    classify_tests,
    display_results as display_test_results,
)
from identify_files_to_implement import (
    classify_files,
    display_results as display_file_results,
    get_functions_needing_editing,
    detect_circular_imports,
    refactor_imports,
)
from rich.console import Console
from rich.panel import Panel
from rich.align import Align

console = Console()


def extract_summary(output: str) -> str:
    """
    Extracts the summary line from pytest output.

    Args:
        output (str): The complete output from pytest.

    Returns:
        str: The summary line containing pass/fail information.
    """
    lines = output.strip().split('\n')
    summary_line = ""
    # Iterate from the end to find the summary line
    for line in reversed(lines):
        if re.search(r'\d+ (failed|passed|xfailed|warnings)', line):
            summary_line = line.strip()
            break
    return summary_line


def run_test(test_identifier: str, library_path: Path) -> bool:
    """
    Runs a single pytest test case and extracts the summary line.

    Args:
        test_identifier (str): The pytest test identifier (e.g., "tests/test_autodiff.py::TestClass::test_chain_rule1").
        library_path (Path): The path to the library directory.

    Returns:
        bool: True if the test passed, False otherwise.
    """
    try:
        # Run the test using subprocess with minimal output
        result = subprocess.run(
            ["pytest", "-q", "--tb=no", test_identifier],
            cwd=library_path,
            capture_output=True,
            text=True
        )

        # Extract the summary line
        summary = extract_summary(result.stdout + result.stderr)
        if summary:
            console.print(summary)
        else:
            console.print("[red]No summary found for the test.[/red]")

        # Determine if the test passed
        if result.returncode == 0:
            return True
        else:
            return False

    except Exception as e:
        console.print(f"[red]Error running test {test_identifier}: {e}[/red]")
        return False


def run_all_tests(library_path: Path) -> bool:
    """
    Runs all tests in the library using pytest and extracts the summary line.

    Args:
        library_path (Path): The path to the library directory.

    Returns:
        bool: True if all tests passed, False otherwise.
    """
    try:
        # Run all tests using subprocess with minimal output
        result = subprocess.run(
            ["pytest", "-q", "--tb=no"],
            cwd=library_path,
            capture_output=True,
            text=True
        )

        # Extract the summary line
        summary = extract_summary(result.stdout + result.stderr)
        if summary:
            console.print(summary)
        else:
            console.print("[red]No summary found for the overall tests.[/red]")

        if result.returncode == 0:
            return True
        else:
            return False

    except Exception as e:
        console.print(f"[red]Error running all tests in {library_path}: {e}[/red]")
        return False


def main():
    base_dir = Path('.').resolve()

    # Step 1: Extract test cases and files to implement
    console.print("[bold blue]Step 1: Extracting test cases and files to implement[/bold blue]")

    # Define directories to exclude
    exclude_dirs = {".venv", "venv", "env", ".env", "site-packages"}

    libraries = find_libraries(base_dir, recursive=True)
    if not libraries:
        console.print("[red]No libraries found.[/red]")
        sys.exit(1)

    # Extract test cases
    test_classification = classify_tests(
        libraries,
        exclude_files=set([
            "conftest.py", "setup.py", "setup.cfg", "requirements.txt",
            "requirements.extra.txt", "README.md"
        ]),
        exclude_patterns=set(["*.egg-info", "build", "dist", "__pycache__", "venv", ".venv", "env", ".env"]),
    )

    # Identify files needing implementation
    file_classification = classify_files(
        libraries,
        exclude_files=set([
            "__init__.py", "__main__.py", "conftest.py",
            "setup.py", "setup.cfg", "requirements.txt",
            "requirements.extra.txt", "README.md"
        ]),
        exclude_patterns=set(["*.egg-info", "build", "dist", "__pycache__", "venv", ".venv", "env", ".env"]),
    )

    # Display results
    console.print("[bold green]Extracted Test Cases:[/bold green]")
    display_test_results(test_classification)

    console.print("[bold green]Files Needing Implementation:[/bold green]")
    display_file_results(file_classification)

    # Step 2: Detect and Refactor Circular Imports
    console.print("[bold blue]Step 2: Detecting and Refactoring Circular Imports[/bold blue]")

    for lib in libraries:
        lib_name = lib.name
        for file_relative_path in file_classification.get(lib_name, {}):
            file_path = lib / file_relative_path
            if detect_circular_imports(file_path):
                console.print(f"[yellow]Circular import detected in {file_path}. Refactoring imports...[/yellow]")
                refactor_imports(file_path)
                console.print(f"[green]Refactored imports in {file_path} to use local imports.[/green]")

    # Step 3: Generate dependency graph (simplified)
    console.print("[bold blue]Step 3: Generating dependency graph[/bold blue]")

    functions_to_implement = []

    for lib in libraries:
        lib_name = lib.name
        if lib_name not in file_classification:
            continue
        for file_relative_path in file_classification[lib_name]:
            file_path = lib / file_relative_path
            # Extract functions needing implementation using the imported function
            try:
                functions = get_functions_needing_editing(file_path)
                for func_name in functions:
                    functions_to_implement.append({
                        'library': lib_name,
                        'file': file_path,
                        'function': func_name,
                        'dependencies': []  # Simplified for now
                    })
            except Exception as e:
                console.print(f"[red]Failed to parse file {file_path}: {e}[/red]")
                continue

    # Step 4: Group functions by file for processing
    console.print("[bold blue]Step 4: Grouping functions by file for processing[/bold blue]")

    # Create a new list of subsets based on file order
    functions_by_file = defaultdict(list)

    for func_info in functions_to_implement:
        file_path = func_info['file']
        functions_by_file[file_path].append(func_info)

    # Convert to a list of subsets, where each subset is a list of functions from a single file
    subsets = list(functions_by_file.values())

    # New: Display the subsets based on file order
    console.print("[bold green]Processing functions grouped by file order:[/bold green]")
    for index, subset in enumerate(subsets):
        file_path = subset[0]['file']
        function_names = [func_info['function'] for func_info in subset]
        console.print(f"[bold yellow]Subset {index + 1}: {file_path.relative_to(base_dir)}[/bold yellow] - {', '.join(function_names)}")

    # Step 5: Iteratively implement functions using Aider (file-by-file approach)
    console.print("[bold blue]Step 5: Iteratively implementing functions using Aider (file-by-file approach)[/bold blue]")

    subset_count = len(subsets)
    for subset_index, subset in enumerate(subsets):
        lib_name = subset[0]['library']
        library_path = next(lib for lib in libraries if lib.name == lib_name)
        file_path = subset[0]['file']

        # Display the functions in the current file subset
        function_names = [func_info['function'] for func_info in subset]
        console.print(f"[bold yellow]Processing file {file_path.relative_to(base_dir)} (Subset {subset_index + 1}/{subset_count})[/bold yellow]")
        console.print(f"[bold cyan]Functions to implement:[/bold cyan] {', '.join(function_names)}")

        retry_count = 0
        max_retries = 2
        success = False

        while retry_count < max_retries and not success:
            # Prepare the prompt for Aider
            prompt = f"Implement the following functions in {file_path.relative_to(library_path)}: {', '.join(function_names)}"
            console.print(f"[bold cyan]Prompt to Aider:[/bold cyan] {prompt}")

            # Construct the Aider command
            cmd = ["aider", "--file", str(file_path.relative_to(library_path)), "--message", prompt]

            # Redirect Aider output to a log file and only show a summary message
            log_file = base_dir / "aider_output.log"
            console.print(f"[bold cyan]Running Aider with command:[/bold cyan] {' '.join(cmd)}")

            try:
                with open(log_file, "w") as log:
                    result = subprocess.run(
                        cmd,
                        cwd=library_path,
                        stdout=log,
                        stderr=log,
                        text=True,
                        input='y\ny\n',  # Automatically answer "yes" to prompts
                        env=os.environ  # Pass the current environment variables
                    )

                # Display concise summary based on Aider's return code
                if result.returncode == 0:
                    console.print("[green]Aider completed the task successfully.[/green]")
                    success = True
                else:
                    console.print("[red]Aider encountered an error. Check aider_output.log for details.[/red]")
                    retry_count += 1

            except Exception as e:
                console.print(f"[red]Error running Aider: {e}[/red]")
                retry_count += 1
                continue

            if not success:
                console.print(f"[red]Failed to implement functions in {file_path.relative_to(library_path)} after {max_retries} attempts[/red]")
            # Proceed to next subset

    # Final Step: Running all test files to evaluate overall performance
    console.print("[bold blue]Step 6: Running all test files to evaluate overall performance[/bold blue]")

    for lib in libraries:
        lib_name = lib.name
        library_path = lib
        console.print(f"[bold magenta]Running all tests in library: {lib_name}[/bold magenta]")
        all_tests_passed = run_all_tests(library_path)

    console.print("[bold green]Process completed. Running the overall performance tests.[/bold green]")


if __name__ == "__main__":
    main()
