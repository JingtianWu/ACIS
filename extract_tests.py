# extract_tests.py

import os
import sys
import ast
import fnmatch
from pathlib import Path
from typing import List, Dict, Set
from collections import defaultdict

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from rich.panel import Panel
    from rich.align import Align
except ImportError:
    print("The 'rich' library is required for this script to run.")
    print("Install it using 'pip install rich' and try again.")
    sys.exit(1)

console = Console()


def is_library_dir(directory: Path) -> bool:
    """
    Determines if a given directory is a library by checking for a 'tests' subdirectory.

    Args:
        directory (Path): The directory to check.

    Returns:
        bool: True if 'tests' subdirectory exists, False otherwise.
    """
    return (directory / "tests").is_dir()


def find_libraries(base_dir: Path, recursive: bool = True, exclude_dirs: Set[str] = None) -> List[Path]:
    """
    Finds all library directories within the base directory, excluding specified directories.

    A library directory is defined as any subdirectory (immediate or nested)
    of the base directory that contains a 'tests' subdirectory.

    Args:
        base_dir (Path): The base directory to search within.
        recursive (bool): Whether to search recursively for libraries.
        exclude_dirs (Set[str], optional): Set of directory names to exclude. Defaults to None.

    Returns:
        List[Path]: A list of Paths to library directories.
    """
    if exclude_dirs is None:
        exclude_dirs = {".venv", "venv", "env", ".env", "site-packages"}

    libraries = []
    if recursive:
        for dir_path in base_dir.rglob("*"):
            if dir_path.is_dir() and is_library_dir(dir_path):
                # Check if the directory is within any excluded directory
                if any(part in exclude_dirs for part in dir_path.parts):
                    continue
                libraries.append(dir_path)
    else:
        for item in base_dir.iterdir():
            if item.is_dir() and is_library_dir(item):
                if any(part in exclude_dirs for part in item.parts):
                    continue
                libraries.append(item)
    return libraries


def collect_test_files(
    library_dir: Path, exclude_files: Set[str], exclude_patterns: Set[str]
) -> List[Path]:
    """
    Recursively collects Python test files from the library directory, excluding specified files and patterns.

    Args:
        library_dir (Path): The library directory to scan.
        exclude_files (Set[str]): Exact filenames to exclude.
        exclude_patterns (Set[str]): Glob patterns to exclude.

    Returns:
        List[Path]: A list of Paths to Python test files.
    """
    test_files = []
    excluded_dirs = {"build", "dist", "__pycache__", "venv", ".venv", "env", ".env"}

    for file_path in library_dir.rglob("test_*.py"):
        # Exclude special files
        if file_path.name in exclude_files:
            continue
        # Exclude files in excluded directories
        if any(part in excluded_dirs for part in file_path.parts):
            continue
        # Exclude files matching excluded patterns
        if any(fnmatch.fnmatch(file_path.name, pattern) for pattern in exclude_patterns):
            continue
        test_files.append(file_path)
    return test_files


def file_contains_tests(file_path: Path) -> bool:
    """
    Determines if a Python test file contains test classes or test functions.

    Args:
        file_path (Path): The path to the Python test file.

    Returns:
        bool: True if the file contains test classes or test functions, False otherwise.
    """
    try:
        with file_path.open("r", encoding="utf-8") as f:
            file_content = f.read()
    except (UnicodeDecodeError, FileNotFoundError):
        return False

    try:
        tree = ast.parse(file_content, filename=str(file_path))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        # Check for test classes inheriting from unittest.TestCase
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Attribute):
                    if (
                        base.attr == "TestCase"
                        and isinstance(base.value, ast.Name)
                        and base.value.id == "unittest"
                    ):
                        return True
                elif isinstance(base, ast.Name):
                    if base.id == "TestCase":
                        return True
        # Check for test functions (functions starting with 'test_')
        elif isinstance(node, ast.FunctionDef):
            if node.name.startswith("test_"):
                return True
    return False


def get_target_test_files(
    library_dir: Path, exclude_files: Set[str], exclude_patterns: Set[str]
) -> List[Path]:
    """
    Retrieves a list of Python test files within a library that contain test cases.

    Args:
        library_dir (Path): The path to the library directory.
        exclude_files (Set[str]): Exact filenames to exclude.
        exclude_patterns (Set[str]): Glob patterns to exclude.

    Returns:
        List[Path]: A list of Paths to Python test files containing test cases.
    """
    test_files = collect_test_files(library_dir, exclude_files, exclude_patterns)
    target_files = []

    for file in test_files:
        if file_contains_tests(file):
            target_files.append(file)

    return target_files


def extract_test_cases(file_path: Path) -> Dict[str, Dict[str, List[str]]]:
    """
    Extracts test classes and test functions from a Python test file.

    Args:
        file_path (Path): The path to the Python test file.

    Returns:
        Dict[str, Dict[str, List[str]]]: A dictionary with keys 'classes' and 'functions'.
            'classes' maps class names to lists of test function names.
            'functions' is a list of standalone test function names.
    """
    test_cases = {"classes": defaultdict(list), "functions": []}

    try:
        with file_path.open("r", encoding="utf-8") as f:
            file_content = f.read()
    except (UnicodeDecodeError, FileNotFoundError):
        return test_cases

    try:
        tree = ast.parse(file_content, filename=str(file_path))
    except SyntaxError:
        return test_cases

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if the class inherits from unittest.TestCase or similar
            inherits_testcase = False
            for base in node.bases:
                if isinstance(base, ast.Attribute):
                    if (
                        base.attr == "TestCase"
                        and isinstance(base.value, ast.Name)
                        and base.value.id == "unittest"
                    ):
                        inherits_testcase = True
                elif isinstance(base, ast.Name):
                    if base.id == "TestCase":
                        inherits_testcase = True
            if inherits_testcase:
                # Collect test functions within the class
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) and child.name.startswith('test_'):
                        test_cases["classes"][node.name].append(child.name)
        elif isinstance(node, ast.FunctionDef):
            if node.name.startswith("test_"):
                test_cases["functions"].append(node.name)

    return test_cases


def classify_tests(
    libraries: List[Path],
    exclude_files: Set[str],
    exclude_patterns: Set[str],
) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    """
    Classifies test cases by their respective libraries.

    Args:
        libraries (List[Path]): List of library directories.
        exclude_files (Set[str]): Exact filenames to exclude.
        exclude_patterns (Set[str]): Glob patterns to exclude.

    Returns:
        Dict[str, Dict[str, Dict[str, List[str]]]]: A nested dictionary mapping library names to test files and their test cases.
            Structure:
            {
                "library1": {
                    "tests/test_module1.py": {
                        "classes": {
                            "TestClass1": ["test_func1", "test_func2"],
                            ...
                        },
                        "functions": ["test_func3", ...]
                    },
                    ...
                },
                ...
            }
    """
    classification = defaultdict(lambda: defaultdict(lambda: {"classes": defaultdict(list), "functions": []}))

    for lib in libraries:
        test_files = get_target_test_files(lib, exclude_files, exclude_patterns)
        for test_file in test_files:
            test_cases = extract_test_cases(test_file)
            relative_path = str(test_file.relative_to(lib))
            if test_cases["classes"]:
                classification[lib.name][relative_path]["classes"].update(test_cases["classes"])
            if test_cases["functions"]:
                classification[lib.name][relative_path]["functions"].extend(test_cases["functions"])

    return classification


def display_results(classification: Dict[str, Dict[str, Dict[str, List[str]]]]) -> None:
    """
    Displays the classification results in a structured table format.

    Args:
        classification (Dict[str, Dict[str, Dict[str, List[str]]]]): The classified test cases per library.
    """
    if not classification:
        console.print("[bold green]No test cases were found.[/bold green]")
        return

    # Define fixed colors for consistency
    library_color = "blue"          # Color for library name in the title
    header_color = "magenta"        # Color for the table header
    border_color = "green"          # Border color for the panels
    class_color = "cyan"             # Color for test classes
    function_color = "yellow"        # Color for test functions

    for lib, tests in sorted(classification.items()):
        # Create separate tables for classes and functions if they exist
        tables = []
        for test_file, test_content in tests.items():
            if test_content["classes"]:
                for class_name, functions in test_content["classes"].items():
                    class_table = Table(
                        title=f"Library: [bold {library_color}]{lib}[/bold {library_color}] - [bold]Test Class: {class_name}[/bold]",
                        box=box.ROUNDED,
                        show_header=True,
                        header_style=f"bold {header_color}"
                    )
                    class_table.add_column("Test Function Name", style=function_color, no_wrap=True)
                    for func in functions:
                        class_table.add_row(f"{test_file}::{class_name}::{func}")
                    tables.append(class_table)

            if test_content["functions"]:
                function_table = Table(
                    title=f"Library: [bold {library_color}]{lib}[/bold {library_color}] - [bold]Standalone Test Functions[/bold]",
                    box=box.ROUNDED,
                    show_header=True,
                    header_style=f"bold {header_color}"
                )
                function_table.add_column("Test Function Name", style=function_color, no_wrap=True)
                for func in test_content["functions"]:
                    function_table.add_row(f"{test_file}::{func}")
                tables.append(function_table)

        # Combine tables into panels
        for table in tables:
            panel = Panel(
                Align.left(table),
                title=f"[bold green]{table.title}[/bold green]",
                border_style=border_color,
                padding=(1, 2)
            )
            console.print(panel)
