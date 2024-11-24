# identify_files_to_implement.py

import ast
import fnmatch
from pathlib import Path
from typing import List, Dict, Set
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.align import Align

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
    Recursively collects Python files from the library directory, including test files,
    and excluding specified files and patterns.

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
        # Exclude files in excluded directories
        if any(part in excluded_dirs for part in file_path.parts):
            continue
        # Exclude files matching excluded patterns
        if any(fnmatch.fnmatch(file_path.name, pattern) for pattern in exclude_patterns):
            continue
        python_files.append(file_path)
    return python_files


def get_functions_needing_editing(file_path: Path) -> List[str]:
    """
    Determines which functions or methods in a Python file need implementation.

    Only includes functions that contain 'raise NotImplementedError(...)'.

    Args:
        file_path (Path): The path to the Python file.

    Returns:
        List[str]: A list of function names that need implementation.
    """
    functions_needing_implementation = []
    special_methods_to_ignore = {"__init__", "__call__", "__str__", "__repr__"}

    try:
        with file_path.open("r", encoding="utf-8") as f:
            file_content = f.read()
    except (UnicodeDecodeError, FileNotFoundError):
        return functions_needing_implementation

    try:
        tree = ast.parse(file_content, filename=str(file_path))
    except SyntaxError:
        return functions_needing_implementation

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            function_name = node.name

            # Skip special methods
            if function_name in special_methods_to_ignore:
                continue

            # Check if the function body contains 'raise NotImplementedError(...)'
            has_not_implemented_error = False
            for stmt in node.body:
                if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
                    func = stmt.exc.func
                    # Ensure it is a 'NotImplementedError' call
                    if (
                        (isinstance(func, ast.Name) and func.id == "NotImplementedError") or
                        (isinstance(func, ast.Attribute) and func.attr == "NotImplementedError")
                    ):
                        has_not_implemented_error = True
                        break

            # Only add functions with 'raise NotImplementedError(...)'
            if has_not_implemented_error:
                functions_needing_implementation.append(function_name)

    # Deduplicate the list and return
    return list(set(functions_needing_implementation))


def detect_circular_imports(file_path: Path) -> bool:
    """
    Detects if a Python file contains imports that may cause circular dependencies.

    Args:
        file_path (Path): The path to the Python file.

    Returns:
        bool: True if potential circular imports are detected, False otherwise.
    """
    try:
        with file_path.open("r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except Exception:
        return False

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_name = node.module
            if module_name and module_name.startswith("minitorch"):
                imports.append(module_name)

    # Simple heuristic: if a file imports tensor_functions and tensor, consider it potentially circular
    if any("tensor_functions" in imp for imp in imports) and any("tensor" in imp for imp in imports):
        return True
    return False


def refactor_imports(file_path: Path) -> None:
    """
    Refactors imports in a Python file to use local imports to avoid circular dependencies.

    Args:
        file_path (Path): The path to the Python file.
    """
    try:
        with file_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        for line in lines:
            # Refactor top-level imports of Tensor to local imports
            if "from .tensor import Tensor" in line:
                # We'll remove the top-level import and add it inside functions
                continue
            new_lines.append(line)

        new_code = "".join(new_lines)

        # Insert local import inside functions that require Tensor
        if "Tensor" in new_code:
            # For simplicity, we'll insert a local import at the beginning of each function that uses Tensor
            # This requires parsing the AST again to find function definitions that use Tensor
            tree = ast.parse(new_code, filename=str(file_path))
            function_names = set()

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    for sub_node in ast.walk(node):
                        if isinstance(sub_node, ast.Name) and sub_node.id == "Tensor":
                            function_names.add(node.name)
                            break
                        elif isinstance(sub_node, ast.Attribute) and sub_node.attr == "Tensor":
                            function_names.add(node.name)
                            break

            if function_names:
                # Insert local imports for Tensor
                updated_lines = new_code.split('\n')
                for i, line in enumerate(updated_lines):
                    if line.strip().startswith("def "):
                        func_def = line.strip()
                        func_name = func_def.split()[1].split('(')[0]
                        if func_name in function_names:
                            # Insert 'from .tensor import Tensor' after function definition
                            updated_lines.insert(i + 1, "    from .tensor import Tensor")
                new_code = '\n'.join(updated_lines)

        with file_path.open("w", encoding="utf-8") as f:
            f.write(new_code)

    except Exception as e:
        console.print(f"[red]Failed to refactor imports in {file_path}: {e}[/red]")


def get_target_files(
    library_dir: Path, exclude_files: Set[str], exclude_patterns: Set[str], use_concurrency: bool = True, max_workers: int = None
) -> Dict[str, Dict[str, List[str]]]:
    """
    Retrieves a mapping of Python files within a library to the functions that need editing.

    Args:
        library_dir (Path): The path to the library directory.
        exclude_files (Set[str]): Exact filenames to exclude.
        exclude_patterns (Set[str]): Glob patterns to exclude.
        use_concurrency (bool): Whether to use concurrency for processing.
        max_workers (int): Maximum number of worker processes.

    Returns:
        Dict[str, Dict[str, List[str]]]: A mapping from library name to file paths and their functions needing editing.
            Structure:
            {
                "library1": {
                    "file1.py": ["func1", "func2"],
                    "file2.py": ["func3"],
                    ...
                },
                ...
            }
    """
    python_files = collect_python_files(library_dir, exclude_files, exclude_patterns)
    target_files = defaultdict(dict)

    if use_concurrency:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {executor.submit(get_functions_needing_editing, file): file for file in python_files}
            for future in as_completed(future_to_file):
                file = future_to_file[future]
                try:
                    functions = future.result()
                    if functions:
                        relative_path = file.relative_to(library_dir)
                        target_files[library_dir.name][str(relative_path)] = functions
                except Exception as e:
                    console.print(f"[red]Error processing file {file}: {e}[/red]")
    else:
        for file in python_files:
            try:
                functions = get_functions_needing_editing(file)
                if functions:
                    relative_path = file.relative_to(library_dir)
                    target_files[library_dir.name][str(relative_path)] = functions
            except Exception as e:
                console.print(f"[red]Error processing file {file}: {e}[/red]")

    return target_files


def classify_files(libraries: List[Path], exclude_files: Set[str], exclude_patterns: Set[str], use_concurrency: bool = True, max_workers: int = None) -> Dict[str, Dict[str, List[str]]]:
    """
    Classifies files needing edits by their respective libraries, including function names.

    Args:
        libraries (List[Path]): List of library directories.
        exclude_files (Set[str]): Exact filenames to exclude.
        exclude_patterns (Set[str]): Glob patterns to exclude.
        use_concurrency (bool): Whether to use concurrency for processing.
        max_workers (int): Maximum number of worker processes.

    Returns:
        Dict[str, Dict[str, List[str]]]: A dictionary mapping library names to files and their functions needing implementation.
            Structure:
            {
                "library1": {
                    "file1.py": ["func1", "func2"],
                    "file2.py": ["func3"],
                    ...
                },
                ...
            }
    """
    classification = defaultdict(dict)

    for lib in libraries:
        target_files = get_target_files(lib, exclude_files, exclude_patterns, use_concurrency, max_workers)
        for lib_name, files in target_files.items():
            classification[lib_name].update(files)

    return classification


def display_results(classification: Dict[str, Dict[str, List[str]]]) -> None:
    """
    Displays the classification results in a structured table format.

    Args:
        classification (Dict[str, Dict[str, List[str]]]): The classified files and functions per library.
    """
    if not classification:
        console.print("[bold green]No files needing edits were found.[/bold green]")
        return

    # Define fixed colors for consistency
    library_color = "blue"          # Color for library name in the title
    header_color = "magenta"        # Color for the table header
    border_color = "green"          # Border color for the panels
    file_color = "cyan"             # Color for file list entries
    function_color = "yellow"       # Color for function names

    for lib, files in sorted(classification.items()):
        # Create a table for each library with uniform colors
        table = Table(
            title=f"Library: [bold {library_color}]{lib}[/bold {library_color}]",
            box=box.ROUNDED,
            show_header=True,
            header_style=f"bold {header_color}"
        )
        table.add_column("File Needing Edits", style=file_color, no_wrap=True)
        table.add_column("Functions Needing Implementation", style=function_color, no_wrap=True)

        for file, functions in sorted(files.items()):
            functions_str = ', '.join(functions)
            table.add_row(file, functions_str)

        # Add the table to a panel for better aesthetics with a uniform border color
        panel = Panel(
            Align.left(table),
            title=f"[bold green]Files in {lib}[/bold green]",
            border_style=border_color,
            padding=(1, 2)
        )
        console.print(panel)