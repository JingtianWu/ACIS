# main.py

import sys
import ast
import subprocess
from pathlib import Path
from collections import defaultdict
from typing import Dict, List
import re

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
    generate_dependency_graph,
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

def determine_implementation_order(functions_to_implement):
    """Determine the order of functions to implement."""
    functions_by_file = defaultdict(list)
    for func_info in functions_to_implement:
        functions_by_file[func_info['file']].append(func_info)
    return list(functions_by_file.values())

def map_source_to_test_files(source_files, library_path):
    """Map source files to their corresponding test files."""
    test_identifiers_to_run = []
    for source_file in source_files:
        source_filename = source_file.name
        test_filename = 'test_' + source_filename
        test_file_path = library_path / 'tests' / test_filename
        if test_file_path.exists():
            test_identifiers_to_run.extend(parse_test_identifiers(test_file_path, library_path))
    return test_identifiers_to_run

def parse_test_identifiers(test_file_path, library_path):
    """Parse a test file to extract test identifiers."""
    try:
        with test_file_path.open('r', encoding='utf-8') as f:
            test_content = f.read()
        test_tree = ast.parse(test_content, filename=str(test_file_path))
        test_identifiers = []
        for node in ast.walk(test_tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) and child.name.startswith('test_'):
                        test_identifier = f"{test_file_path.relative_to(library_path)}::{class_name}::{child.name}"
                        test_identifiers.append(test_identifier)
            elif isinstance(node, ast.FunctionDef):
                if node.name.startswith('test_'):
                    test_identifier = f"{test_file_path.relative_to(library_path)}::{node.name}"
                    test_identifiers.append(test_identifier)
        return test_identifiers
    except Exception as e:
        console.print(f"[red]Failed to parse test file {test_file_path}: {e}[/red]")
        return []

def main():
    base_dir = Path('.').resolve()

    # Step 1: Extract test cases and files to implement
    console.print("[bold blue]Step 1: Extracting test cases and files to implement[/bold blue]")

    # Define directories to exclude
    # exclude_dirs = {".venv", "venv", "env", ".env", "site-packages"}

    libraries = find_libraries(base_dir)
    if not libraries:
        console.print("[red]No libraries found.[/red]")
        sys.exit(1)

    # Extract test cases
    test_classification = classify_tests(libraries)

    # Identify files needing implementation
    file_classification = classify_files(libraries)

    # Display results
    console.print("[bold green]Extracted Test Cases:[/bold green]")
    display_test_results(test_classification)

    console.print("[bold green]Files Needing Implementation:[/bold green]")
    display_file_results(file_classification)

    # Step 2: Generate dependency graph (simplified)
    console.print("[bold blue]Step 2: Generating dependency graph[/bold blue]")    
    functions_to_implement = generate_dependency_graph(libraries, file_classification)

    # Step 3: Determine implementation order
    console.print("[bold blue]Step 3: Determining implementation order[/bold blue]")
    subsets = determine_implementation_order(functions_to_implement)

    # Step 4: Iteratively implement functions
    console.print("[bold blue]Step 4: Iteratively implementing functions[/bold blue]")

    subset_count = len(subsets)
    for subset_index, subset in enumerate(subsets):
        lib_name = subset[0]['library']
        library_path = next(lib for lib in libraries if lib.name == lib_name)
        console.print(f"[bold yellow]Processing subset {subset_index + 1}/{subset_count} for library '{lib_name}'[/bold yellow]")

        retry_count = 0
        max_retries = 3
        success = False

        # Determine the test identifiers to run for this subset
        source_files = set(func_info['file'] for func_info in subset)
        test_identifiers_to_run = map_source_to_test_files(source_files, library_path)
        
        if not test_identifiers_to_run:
            console.print(f"[yellow]No tests found for subset {subset_index + 1}. Skipping test execution.[/yellow]")
            success = True
            continue

        while retry_count < max_retries and not success:
            console.print(f"Attempt {retry_count + 1} to implement functions in subset {subset_index + 1}")
            functions_in_subset = [func_info['function'] for func_info in subset]
            prompt = f"Implement functions: {functions_in_subset}"
            console.print(f"[bold cyan]Prompt to LLM:[/bold cyan] {prompt}")

            # Since LLM is not connected, no implementation occurs

            # Run corresponding tests
            all_tests_passed = True
            for test_identifier in test_identifiers_to_run:
                console.print(f"[bold magenta]Running test case: {test_identifier}[/bold magenta]")
                test_passed = run_test(test_identifier, library_path)
                if not test_passed:
                    all_tests_passed = False

            if all_tests_passed:
                console.print(f"[green]All tests passed for subset {subset_index + 1}[/green]")
                success = True
            else:
                console.print(f"[red]Tests failed for subset {subset_index + 1}[/red]")
                retry_count += 1

        if not success:
            console.print(f"[red]Failed to implement functions in subset {subset_index + 1} after {max_retries} attempts[/red]")
            # Proceed to next subset

    # Step 5: Running all test files to evaluate overall performance
    console.print("[bold blue]Step 5: Running all test files to evaluate overall performance[/bold blue]")

    for lib in libraries:
        lib_name = lib.name
        library_path = lib
        console.print(f"[bold magenta]Running all tests in library: {lib_name}[/bold magenta]")
        all_tests_passed = run_all_tests(library_path)

    console.print("[bold green]Process completed. Running the overall performance tests.[/bold green]")


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


if __name__ == "__main__":
    main()
