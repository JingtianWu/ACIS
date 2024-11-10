# main.py

import sys
import ast
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


def parse_failed_tests(summary_line: str) -> int:
    """
    Parses the summary line to extract the number of failed tests.

    Args:
        summary_line (str): The summary line from pytest output.

    Returns:
        int: The number of failed tests.
    """
    match = re.search(r'(\d+) failed', summary_line)
    if match:
        return int(match.group(1))
    else:
        return 0


def main():
    base_dir = Path('.').resolve()

    # Step 0: Initialize Git repository and make initial commit
    console.print("[bold blue]Step 0: Initializing Git repository and capturing baseline[/bold blue]")
    if not (base_dir / '.git').exists():
        console.print("[bold cyan]Initializing Git repository...[/bold cyan]")
        subprocess.run(['git', 'init'], cwd=base_dir)
        subprocess.run(['git', 'add', '.'], cwd=base_dir)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=base_dir)
        console.print("[green]Git repository initialized and initial commit made.[/green]")
    else:
        console.print("[green]Git repository already initialized.[/green]")

    # Step 1: Extract test cases and files to implement
    console.print("[bold blue]Step 1: Extracting test cases and files to implement[/bold blue]")

    # Define directories to exclude
    exclude_dirs = {".venv", "venv", "env", ".env", "site-packages"}

    libraries = find_libraries(base_dir, exclude_dirs=exclude_dirs)
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

    # Step 2: Generate dependency graph (simplified)
    console.print("[bold blue]Step 2: Generating dependency graph[/bold blue]")

    functions_to_implement = []

    for lib in libraries:
        lib_name = lib.name
        if lib_name not in file_classification:
            continue
        for file_relative_path in file_classification[lib_name]:
            file_path = lib / file_relative_path
            # Parse the file to get function names
            try:
                with file_path.open('r', encoding='utf-8') as f:
                    file_content = f.read()
                tree = ast.parse(file_content, filename=str(file_path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        functions_to_implement.append({
                            'library': lib_name,
                            'file': file_path,
                            'function': node.name,
                            'dependencies': []  # Simplified for now
                        })
            except Exception as e:
                console.print(f"[red]Failed to parse file {file_path}: {e}[/red]")
                continue

    # Step 3: Determine implementation order
    console.print("[bold blue]Step 3: Determining implementation order[/bold blue]")

    functions_by_file = defaultdict(list)
    for func_info in functions_to_implement:
        functions_by_file[func_info['file']].append(func_info)

    subsets = list(functions_by_file.values())

    # Step 4: Capture initial test results as baseline
    console.print("[bold blue]Step 4: Capturing initial test results as baseline[/bold blue]")
    baseline_failed_tests = {}
    for lib in libraries:
        lib_name = lib.name
        library_path = lib
        console.print(f"[bold cyan]Running initial tests for library: {lib_name}[/bold cyan]")
        summary_line = run_all_tests(library_path)
        failed_tests = parse_failed_tests(summary_line)
        baseline_failed_tests[lib_name] = failed_tests
        console.print(f"[green]Initial failed tests for {lib_name}: {failed_tests}[/green]")

    # Step 5: Iteratively implement functions using Aider
    console.print("[bold blue]Step 5: Iteratively implementing functions using Aider[/bold blue]")

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
        test_identifiers_to_run = []

        for source_file in source_files:
            # Map source file to test file
            source_filename = source_file.name
            test_filename = 'test_' + source_filename
            test_file_path = library_path / 'tests' / test_filename
            if test_file_path.exists():
                # Extract test functions within classes and standalone functions
                try:
                    with test_file_path.open('r', encoding='utf-8') as f:
                        test_content = f.read()
                    test_tree = ast.parse(test_content, filename=str(test_file_path))
                except Exception as e:
                    console.print(f"[red]Failed to parse test file {test_file_path}: {e}[/red]")
                    continue

                for node in ast.walk(test_tree):
                    if isinstance(node, ast.ClassDef):
                        class_name = node.name
                        for child in node.body:
                            if isinstance(child, ast.FunctionDef) and child.name.startswith('test_'):
                                test_identifier = f"{test_file_path.relative_to(library_path)}::{class_name}::{child.name}"
                                test_identifiers_to_run.append(test_identifier)
                    elif isinstance(node, ast.FunctionDef):
                        if node.name.startswith('test_'):
                            test_identifier = f"{test_file_path.relative_to(library_path)}::{node.name}"
                            test_identifiers_to_run.append(test_identifier)

        if not test_identifiers_to_run:
            console.print(f"[yellow]No tests found for subset {subset_index + 1}. Skipping test execution.[/yellow]")
            success = True
            continue

        while retry_count < max_retries and not success:
            console.print(f"Attempt {retry_count + 1} to implement functions in subset {subset_index + 1}")
            functions_in_subset = [func_info['function'] for func_info in subset]
            prompt = f"Implement the following functions: {', '.join(functions_in_subset)}"
            console.print(f"[bold cyan]Prompt to Aider:[/bold cyan] {prompt}")

            # Prepare the list of files
            files_in_subset = set(func_info['file'] for func_info in subset)
            # Convert files to paths relative to the library_path
            file_paths = [str(file_path.relative_to(library_path)) for file_path in files_in_subset]

            # Construct the Aider command
            cmd = ["aider"]
            for file_path in file_paths:
                cmd.extend(["--file", file_path])
            cmd.extend(["--message", prompt])

            # Get the current Git commit hash
            result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=base_dir, capture_output=True, text=True)
            if result.returncode == 0:
                previous_commit_hash = result.stdout.strip()
            else:
                console.print("[red]Failed to get current Git commit hash.[/red]")
                previous_commit_hash = None

            # Run Aider via subprocess with automatic "yes" answers
            console.print(f"[bold cyan]Running Aider with command:[/bold cyan] {' '.join(cmd)}")
            try:
                result = subprocess.run(
                    cmd,
                    cwd=library_path,
                    capture_output=True,
                    text=True,
                    input='y\ny\n',  # Automatically answer "yes" to prompts
                    env=os.environ  # Pass the current environment variables
                )
                # Print the output from Aider
                console.print(result.stdout)
                console.print(result.stderr)

                # Check if Aider exited successfully
                if result.returncode != 0:
                    console.print(f"[red]Aider exited with error code {result.returncode}[/red]")
                    # Decide whether to retry or not
                    retry_count += 1
                    continue

            except Exception as e:
                console.print(f"[red]Error running Aider: {e}[/red]")
                retry_count += 1
                continue

            # After code generation, run all tests in the library
            console.print(f"[bold magenta]Running all tests in library: {lib_name}[/bold magenta]")
            summary_line = run_all_tests(library_path)
            current_failed_tests = parse_failed_tests(summary_line)
            console.print(f"[green]Current failed tests for {lib_name}: {current_failed_tests}[/green]")

            # Compare with baseline
            if current_failed_tests < baseline_failed_tests[lib_name]:
                console.print(f"[green]Performance improved! Failed tests reduced from {baseline_failed_tests[lib_name]} to {current_failed_tests}[/green]")
                # Commit the changes
                subprocess.run(['git', 'add', '.'], cwd=base_dir)
                commit_message = f"Implemented functions in subset {subset_index + 1}"
                subprocess.run(['git', 'commit', '-m', commit_message], cwd=base_dir)
                console.print(f"[green]Changes committed with message: '{commit_message}'[/green]")
                # Update baseline
                baseline_failed_tests[lib_name] = current_failed_tests
                success = True
            else:
                console.print(f"[red]No performance improvement. Reverting changes...[/red]")
                if previous_commit_hash:
                    subprocess.run(['git', 'reset', '--hard', previous_commit_hash], cwd=base_dir)
                    console.print(f"[yellow]Reverted to previous commit: {previous_commit_hash}[/yellow]")
                else:
                    console.print(f"[red]Could not revert changes due to missing commit hash.[/red]")
                retry_count += 1

        if not success:
            console.print(f"[red]Failed to implement functions in subset {subset_index + 1} after {max_retries} attempts[/red]")
            # Proceed to next subset

    # Final Step: Running all test files to evaluate overall performance
    console.print("[bold blue]Final Step: Running all test files to evaluate overall performance[/bold blue]")
    for lib in libraries:
        lib_name = lib.name
        library_path = lib
        console.print(f"[bold magenta]Running all tests in library: {lib_name}[/bold magenta]")
        summary_line = run_all_tests(library_path)
        current_failed_tests = parse_failed_tests(summary_line)
        console.print(f"[green]Final failed tests for {lib_name}: {current_failed_tests}[/green]")

    console.print("[bold green]Process completed. All subsets processed.[/bold green]")


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


def run_all_tests(library_path: Path) -> str:
    """
    Runs all tests in the library using pytest and extracts the summary line.

    Args:
        library_path (Path): The path to the library directory.

    Returns:
        str: The summary line from pytest output.
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

        return summary

    except Exception as e:
        console.print(f"[red]Error running all tests in {library_path}: {e}[/red]")
        return ""


if __name__ == "__main__":
    main()
