# identify_files_to_implement.py

import os
import sys
import ast
import fnmatch
from pathlib import Path
from typing import List, Dict, Set
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

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


def find_libraries(base_dir: Path, recursive: bool = True) -> List[Path]:
    """
    Finds all library directories within the base directory.

    A library directory is defined as any subdirectory (immediate or nested)
    of the base directory that contains a 'tests' subdirectory.

    Args:
        base_dir (Path): The base directory to search within.
        recursive (bool): Whether to search recursively for libraries.

    Returns:
        List[Path]: A list of Paths to library directories.
    """
    libraries = []
    if recursive:
        for dir_path in base_dir.rglob("*"):
            if dir_path.is_dir() and is_library_dir(dir_path):
                libraries.append(dir_path)
    else:
        for item in base_dir.iterdir():
            if item.is_dir() and is_library_dir(item):
                libraries.append(item)
    return libraries


def collect_python_files(library_dir: Path, exclude_files: Set[str], exclude_patterns: Set[str]) -> List[Path]:
    """
    Recursively collects Python files from the library directory, excluding test files and special files.

    Args:
        library_dir (Path): The library directory to scan.
        exclude_files (Set[str]): Exact filenames to exclude.
        exclude_patterns (Set[str]): Glob patterns to exclude.

    Returns:
        List[Path]: A list of Paths to Python files needing edits.
    """
    python_files = []
    excluded_dirs = {"build", "dist", "__pycache__", "venv", ".venv", "env", ".env"}

    for file_path in library_dir.rglob("*.py"):
        # Exclude special files
        if file_path.name in exclude_files:
            continue
        # Exclude files in any 'tests/' subdirectories
        if "tests" in file_path.parts:
            continue
        # Exclude files in excluded directories
        if any(part in excluded_dirs for part in file_path.parts):
            continue
        # Exclude files matching excluded patterns
        if any(fnmatch.fnmatch(file_path.name, pattern) for pattern in exclude_patterns):
            continue
        python_files.append(file_path)
    return python_files


def file_needs_editing(file_path: Path) -> bool:
    """
    Determines if a Python file contains classes or functions with 'pass' or 'raise NotImplementedError'.

    Args:
        file_path (Path): The path to the Python file.

    Returns:
        bool: True if the file contains such classes or functions, False otherwise.
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
        # Check for classes and functions
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            for stmt in node.body:
                if isinstance(stmt, ast.Pass):
                    return True
                if isinstance(stmt, ast.Raise):
                    # Handle different types of Raise nodes
                    if isinstance(stmt.exc, ast.Call):
                        func = stmt.exc.func
                        # Check if the raised exception is NotImplementedError
                        if isinstance(func, ast.Name) and func.id == "NotImplementedError":
                            return True
                        elif isinstance(func, ast.Attribute) and func.attr == "NotImplementedError":
                            return True
        elif isinstance(node, ast.Expr):
            # Check for expressions like '...'
            if isinstance(node.value, ast.Constant) and node.value.value == Ellipsis:
                return True
    return False


def get_target_files(library_dir: Path, exclude_files: Set[str], exclude_patterns: Set[str], use_concurrency: bool = True, max_workers: int = None) -> List[Path]:
    """
    Retrieves a list of Python files within a library that need editing.

    Args:
        library_dir (Path): The path to the library directory.
        exclude_files (Set[str]): Exact filenames to exclude.
        exclude_patterns (Set[str]): Glob patterns to exclude.
        use_concurrency (bool): Whether to use concurrency for processing.
        max_workers (int): Maximum number of worker processes.

    Returns:
        List[Path]: A list of Paths to Python files needing edits.
    """
    python_files = collect_python_files(library_dir, exclude_files, exclude_patterns)
    target_files = []

    if use_concurrency:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {executor.submit(file_needs_editing, file): file for file in python_files}
            for future in as_completed(future_to_file):
                file = future_to_file[future]
                try:
                    if future.result():
                        target_files.append(file)
                except Exception:
                    pass
    else:
        for file in python_files:
            if file_needs_editing(file):
                target_files.append(file)

    return target_files


def classify_files(libraries: List[Path], exclude_files: Set[str], exclude_patterns: Set[str], use_concurrency: bool = True, max_workers: int = None) -> Dict[str, List[str]]:
    """
    Classifies files needing edits by their respective libraries.

    Args:
        libraries (List[Path]): List of library directories.
        exclude_files (Set[str]): Exact filenames to exclude.
        exclude_patterns (Set[str]): Glob patterns to exclude.
        use_concurrency (bool): Whether to use concurrency for processing.
        max_workers (int): Maximum number of worker processes.

    Returns:
        Dict[str, List[str]]: A dictionary mapping library names to lists of file paths.
    """
    classification = defaultdict(list)

    for lib in libraries:
        target_files = get_target_files(lib, exclude_files, exclude_patterns, use_concurrency, max_workers)
        for file in target_files:
            try:
                relative_path = file.relative_to(lib)
                classification[lib.name].append(str(relative_path))
            except ValueError:
                classification[lib.name].append(str(file))
    return classification


def display_results(classification: Dict[str, List[str]]) -> None:
    """
    Displays the classification results in a structured table format.

    Args:
        classification (Dict[str, List[str]]): The classified files per library.
    """
    if not classification:
        console.print("[bold green]No files needing edits were found.[/bold green]")
        return

    # Define fixed colors for consistency
    library_color = "blue"          # Color for library name in the title
    header_color = "magenta"        # Color for the table header
    border_color = "green"          # Border color for the panels
    file_color = "cyan"             # Color for file list entries

    for lib, files in sorted(classification.items()):
        # Create a table for each library with uniform colors
        table = Table(
            title=f"Library: [bold {library_color}]{lib}[/bold {library_color}]",
            box=box.ROUNDED,
            show_header=True,
            header_style=f"bold {header_color}"
        )
        table.add_column("Files Needing Edits", style=file_color, no_wrap=True)

        for file in sorted(files):
            table.add_row(file)

        # Add the table to a panel for better aesthetics with a uniform border color
        panel = Panel(
            Align.left(table),
            title=f"[bold green]Files in {lib}[/bold green]",
            border_style=border_color,
            padding=(1, 2)
        )
        console.print(panel)
