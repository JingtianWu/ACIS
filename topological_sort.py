# topological_sort.py

import os
import ast
from graphlib import TopologicalSorter, CycleError
from collections import defaultdict
from typing import List, Dict, Set, Tuple


class Module:
    def __init__(self, path: str, fqn: str):
        self.path = path
        self.fqn = fqn  # Fully Qualified Name

    def __repr__(self):
        return f"Module(path={self.path}, fqn={self.fqn})"


class ModuleSet:
    def __init__(self, paths: List[str]):
        self.by_path: Dict[str, Module] = {}
        self.by_name: Dict[str, Module] = {}
        self._load_modules(paths)

    def _load_modules(self, paths: List[str]):
        for path in paths:
            if os.path.isfile(path) and path.endswith('.py'):
                fqn = self._get_fqn_from_path(path)
                module = Module(path, fqn)
                self.by_path[path] = module
                self.by_name[fqn] = module
                # Debug Output
                # print(f"Loaded module: {module}")

    def _get_fqn_from_path(self, path: str) -> str:
        # Simplified FQN generation; adjust as needed
        relative_path = os.path.relpath(path, start=os.getcwd())
        fqn = os.path.splitext(relative_path.replace(os.sep, '.'))[0]
        # Debug Output
        # print(f"Path: {path} -> FQN: {fqn}")
        return fqn

    def get_imports(self, module: Module) -> Set[str]:
        with open(module.path, 'r', encoding='utf-8') as file:
            try:
                tree = ast.parse(file.read(), filename=module.path)
            except SyntaxError:
                return set()

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_level_module = alias.name.split('.')[0]
                    imports.add(top_level_module)  # Only top-level module names
                    # Debug Output
                    # print(f"Imported module: {top_level_module}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    if node.level == 0:
                        # Absolute import
                        top_level_module = node.module.split('.')[0]
                        imports.add(node.module)  # Add the full module
                        # Debug Output
                        # print(f"Imported module (absolute): {node.module}")
                    else:
                        # Relative import
                        current_fqn = module.fqn
                        parent_levels = node.level
                        # Split the current_fqn into parts
                        parts = current_fqn.split('.')
                        if parent_levels > len(parts):
                            # Invalid relative import
                            continue
                        base = parts[:-parent_levels]
                        if node.module:
                            full_module = '.'.join(base + node.module.split('.'))
                        else:
                            full_module = '.'.join(base)
                        imports.add(full_module)  # Add the fully qualified module
                        # Debug Output
                        # print(f"Imported module (relative): {full_module}")
                else:
                    # 'from . import something'
                    if node.level > 0:
                        current_fqn = module.fqn
                        parent_levels = node.level
                        parts = current_fqn.split('.')
                        if parent_levels > len(parts):
                            # Invalid relative import
                            continue
                        base = parts[:-parent_levels]
                        full_module = '.'.join(base)
                        imports.add(full_module)  # Add the fully qualified module
                        # Debug Output
                        # print(f"Imported module (relative without module): {full_module}")

        return imports

    def get_function_and_class_references(self, module: Module) -> Set[str]:
        with open(module.path, 'r', encoding='utf-8') as file:
            try:
                tree = ast.parse(file.read(), filename=module.path)
            except SyntaxError:
                return set()

        references = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name):
                        references.add(node.func.value.id)
                elif isinstance(node.func, ast.Name):
                    references.add(node.func.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    references.add(node.value.id)
        return references


def ignore_cycles(graph: Dict[str, Set[str]]) -> List[str]:
    """Attempts to perform topological sort and handles cycles by removing problematic nodes."""
    ts = TopologicalSorter(graph)
    try:
        return list(ts.static_order())
    except CycleError as e:
        cycle_nodes = e.args[1]
        print(f"Cycle detected involving the following nodes: {cycle_nodes}")
        # Remove the first node in the cycle to break it
        node_to_remove = cycle_nodes[0]
        print(f"Removing node {node_to_remove} to resolve cycle.")
        graph.pop(node_to_remove, None)
        return ignore_cycles(graph)


def topological_sort_based_on_dependencies(pkg_paths: List[str]) -> Tuple[List[str], Dict[str, Set[str]]]:
    """Performs a topological sort on the given Python files based on their dependencies.
    
    Args:
        pkg_paths (List[str]): List of file paths to Python modules.
    
    Returns:
        Tuple[List[str], Dict[str, Set[str]]]: A tuple containing the sorted list of file paths
            and the dependency mapping.
    """
    module_set = ModuleSet(pkg_paths)

    import_dependencies: Dict[str, Set[str]] = {}
    for path in sorted(module_set.by_path.keys()):
        module = module_set.by_path[path]
        try:
            imports = module_set.get_imports(module)
            references = module_set.get_function_and_class_references(module)
            # Combine imports and references
            all_dependencies = imports.union(references)
            # Map module names to file paths if they exist in the module_set
            dependencies = set()
            for dep in all_dependencies:
                dep_module = module_set.by_name.get(dep)
                if dep_module:
                    dependencies.add(dep_module.path)
            import_dependencies[path] = dependencies
        except Exception as e:
            print(f"Error processing module {module.fqn}: {e}")
            import_dependencies[path] = set()

    sorted_files = ignore_cycles(import_dependencies.copy())

    return sorted_files, import_dependencies