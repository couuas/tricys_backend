import re
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class LayoutService:
    """
    Service to parse Modelica models for visualization structures (components, connections, layout).
    Ported from tricys_vis logic.
    """

    @staticmethod
    def parse_model_structure(content: str) -> Dict[str, Any]:
        """
        Parses Modelica code content to extract:
        1. Components with layout coordinates (annotation(origin=...))
        2. Connections
        3. Parameters (basic extraction)
        4. Source codes for sub-components
        """
        data = {
            "components": [],
            "connections": [],
            "parameters": [],
            "source_codes": {}
        }

        def strip_line_comments(text: str) -> str:
            return re.sub(r"//.*", "", text)

        def split_declarations(block_text: str) -> List[str]:
            declarations = []
            current = []
            paren_depth = 0
            brace_depth = 0
            bracket_depth = 0

            for char in block_text:
                current.append(char)
                if char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth = max(0, paren_depth - 1)
                elif char == '{':
                    brace_depth += 1
                elif char == '}':
                    brace_depth = max(0, brace_depth - 1)
                elif char == '[':
                    bracket_depth += 1
                elif char == ']':
                    bracket_depth = max(0, bracket_depth - 1)
                elif char == ';' and paren_depth == 0 and brace_depth == 0 and bracket_depth == 0:
                    statement = ''.join(current).strip()
                    if statement:
                        declarations.append(statement)
                    current = []

            remainder = ''.join(current).strip()
            if remainder:
                declarations.append(remainder)

            return declarations

        def split_top_level(text: str, delimiter: str = ',') -> List[str]:
            parts = []
            current = []
            paren_depth = 0
            brace_depth = 0
            bracket_depth = 0
            in_string = False
            string_quote = ''

            for char in text:
                current.append(char)

                if in_string:
                    if char == string_quote:
                        in_string = False
                    continue

                if char in {'"', "'"}:
                    in_string = True
                    string_quote = char
                elif char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth = max(0, paren_depth - 1)
                elif char == '{':
                    brace_depth += 1
                elif char == '}':
                    brace_depth = max(0, brace_depth - 1)
                elif char == '[':
                    bracket_depth += 1
                elif char == ']':
                    bracket_depth = max(0, bracket_depth - 1)
                elif char == delimiter and paren_depth == 0 and brace_depth == 0 and bracket_depth == 0:
                    item = ''.join(current[:-1]).strip()
                    if item:
                        parts.append(item)
                    current = []

            remainder = ''.join(current).strip()
            if remainder:
                parts.append(remainder)
            return parts

        def parse_modelica_value(value_text: str) -> Any:
            text = value_text.strip()
            if not text:
                return ''

            if text.startswith('{') and text.endswith('}'):
                inner = text[1:-1].strip()
                if not inner:
                    return []
                return [parse_modelica_value(part) for part in split_top_level(inner)]

            if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
                return text[1:-1]

            lower_text = text.lower()
            if lower_text == 'true':
                return True
            if lower_text == 'false':
                return False

            try:
                number = float(text)
                if number.is_integer() and not any(token in text.lower() for token in ['.', 'e']):
                    return int(number)
                return number
            except Exception:
                return text

        def format_dimensions(value: Any) -> str:
            if not isinstance(value, list):
                return '()'

            dimensions = []
            current = value
            while isinstance(current, list):
                dimensions.append(len(current))
                current = current[0] if current else None
            return '(' + ','.join(str(dimension) for dimension in dimensions) + ')'

        def strip_annotation(statement: str) -> str:
            annotation_match = re.search(r"\bannotation\s*\(", statement, re.IGNORECASE)
            if not annotation_match:
                return statement.strip()
            return statement[:annotation_match.start()].strip()

        def extract_instance_parameter_entries(statement: str, instance_name: str) -> List[Dict[str, Any]]:
            entries = []
            stripped_statement = strip_annotation(statement)
            constructor_match = re.match(
                rf"^\s*[A-Za-z_][\w\.]*\s+{re.escape(instance_name)}(?:\[[^\]]+\])?\s*\((.*)\)\s*$",
                stripped_statement,
                re.DOTALL,
            )
            if not constructor_match:
                return entries

            constructor_body = constructor_match.group(1).strip()
            if not constructor_body:
                return entries

            for argument in split_top_level(constructor_body):
                if '=' not in argument:
                    continue
                param_name, raw_value = argument.split('=', 1)
                param_name = param_name.strip()
                if not param_name:
                    continue

                parsed_value = parse_modelica_value(raw_value)
                entries.append({
                    'name': f'{instance_name}.{param_name}',
                    'type': 'Unknown',
                    'value': parsed_value,
                    'defaultValue': parsed_value,
                    'comment': '',
                    'dimensions': format_dimensions(parsed_value),
                })

            return entries

        def upsert_parameter_entry(entry: Dict[str, Any], preserve_existing_value: bool = False) -> None:
            existing_index = next((index for index, item in enumerate(data['parameters']) if item.get('name') == entry.get('name')), None)
            if existing_index is None:
                data['parameters'].append(entry)
                return

            existing_entry = data['parameters'][existing_index]
            merged_entry = {**existing_entry, **entry}
            if preserve_existing_value:
                merged_entry['value'] = existing_entry.get('value', merged_entry.get('value'))
                merged_entry['defaultValue'] = existing_entry.get('defaultValue', merged_entry.get('defaultValue'))
            data['parameters'][existing_index] = merged_entry

        # --- 1. Locate Main Model Block ---
        package_match = re.search(r"\bpackage\s+([A-Za-z_]\w*)", content)
        package_name = package_match.group(1) if package_match else None

        model_matches = re.findall(r"\bmodel\s+([A-Za-z_]\w*)", content)
        if model_matches:
            main_model_name = model_matches[-1]
            full_model_name = f"{package_name}.{main_model_name}" if package_name else main_model_name
            data["model_name"] = full_model_name
            cycle_block_pattern = re.compile(rf"((?:within\s+[^;]+;\s*)?model\s+{re.escape(main_model_name)}(.*?)end\s+{re.escape(main_model_name)};)", re.DOTALL | re.IGNORECASE)
            match_block = cycle_block_pattern.search(content)
        else:
            main_model_name = "Cycle"
            data["model_name"] = "example_model.Cycle"
            cycle_block_pattern = re.compile(r"((?:within\s+[^;]+;\s*)?model\s+Cycle(.*?)end\s+Cycle;)", re.DOTALL | re.IGNORECASE)
            match_block = cycle_block_pattern.search(content)
        
        cycle_full_code = match_block.group(1).strip() if match_block else content.strip()
        cycle_content = match_block.group(2) if match_block else content
        data["source_codes"][main_model_name] = cycle_full_code

        # Map: Type -> Instance Names (e.g. "Plasma" -> ["plasma"])
        type_instance_map: Dict[str, List[str]] = {}
        instance_parameter_overrides: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # --- 2. Parse Components [ROBUST STRATEGY] ---
        declaration_section = re.split(
            r"\b(?:equation|algorithm|initial\s+equation|initial\s+algorithm)\b",
            cycle_content,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        origin_pattern = re.compile(r"origin\s*=\s*\{([-\d\.]+)\s*,\s*([-\d\.]+)\}")
        declaration_pattern = re.compile(r"^\s*([A-Za-z_][\w\.]*)\s+([A-Za-z_][\w]*)\b", re.DOTALL)

        keywords = {"Modelica", "import", "parameter", "constant", 
                   "Real", "Integer", "Boolean", "String", 
                   "equation", "algorithm", "initial", "protected", "public",
                   "connect", "annotation", "extends", "replaceable", "final", "input", "output"}

        for statement in split_declarations(declaration_section):
            clean_statement = strip_line_comments(statement).strip()
            if not clean_statement:
                continue

            if clean_statement.lower().startswith("connect"):
                continue

            match = declaration_pattern.match(clean_statement)
            if not match:
                continue

            comp_type = match.group(1)
            comp_name = match.group(2)
            
            if comp_type in keywords:
                continue

            # Basic position defaults
            x, y = 0.0, 0.0
            
            # Check for origin in the statement body
            origin_match = origin_pattern.search(clean_statement)
            if origin_match:
                try:
                    x = float(origin_match.group(1))
                    y = float(origin_match.group(2))
                except: pass
            else:
                 # Auto-layout primitive: spread them out if no layout?
                 # ideally we just let them stack at 0,0 or give random
                 import random
                 x = random.uniform(-80, 80)
                 y = random.uniform(-80, 80)

            data["components"].append({
                "id": comp_name,
                "type": comp_type,
                "position": {"x": x, "y": y},
                "has_layout": bool(origin_match)
            })

            type_instance_map.setdefault(comp_type, []).append(comp_name)
            data["source_codes"][comp_name] = statement.strip()

            instance_entries = extract_instance_parameter_entries(clean_statement, comp_name)
            if instance_entries:
                override_map = instance_parameter_overrides.setdefault(comp_name, {})
                for entry in instance_entries:
                    override_map[entry['name'].split('.', 1)[1]] = entry
                    upsert_parameter_entry(entry)

        # --- 3. Parse Connections ---
        connection_pattern = re.compile(r"connect\s*\(\s*([\w\.]+)\s*,\s*([\w\.]+)\s*\)")
        
        for match in connection_pattern.finditer(cycle_content):
            source_full = match.group(1)
            target_full = match.group(2)
            
            source_comp = source_full.split('.')[0]
            target_comp = target_full.split('.')[0]

            data["connections"].append({
                "from": source_comp,
                "to": target_comp,
                "raw_from": source_full,
                "raw_to": target_full
            })

        # --- 4. Parse Sub-model Parameters & Source ---
        model_def_pattern = re.compile(r"((?:model|block)\s+([A-Za-z_][\w]*)(.*?)end\s+\2;)", re.DOTALL)
        
        for match in model_def_pattern.finditer(content):
            full_code = match.group(1)
            model_type = match.group(2)
            model_body = match.group(3)
            
            if model_type in type_instance_map:
                for instance_name in type_instance_map[model_type]:
                    data["source_codes"][instance_name] = full_code.strip()

                    param_pattern = re.compile(
                        r"parameter\s+([A-Za-z_][\w\.]*)\s+"
                        r"([a-zA-Z0-9_]+)"
                        r"(\s*\[[^\]]+\])?"
                        r"(?:\s*\([^)]*\))?"
                        r"\s*=\s*"
                        r"([^;]*?)"
                        r"\s*(?:\"(.*?)\"\s*)?;"
                    )
                    
                    for p_match in param_pattern.finditer(model_body):
                        p_type = p_match.group(1)
                        p_name = p_match.group(2)
                        p_dims = p_match.group(3) or ''
                        raw_val = p_match.group(4).strip()
                        val = parse_modelica_value(raw_val)

                        key = f"{instance_name}.{p_name}"
                        base_entry = {
                            "name": key,
                            "type": p_type,
                            "value": val,
                            "defaultValue": val,
                            "comment": p_match.group(5).strip() if p_match.group(5) else "",
                            "dimensions": p_dims.strip() if p_dims else format_dimensions(val)
                        }

                        override_entry = instance_parameter_overrides.get(instance_name, {}).get(p_name)
                        if override_entry:
                            merged_entry = {
                                **base_entry,
                                "value": override_entry.get("value", val),
                                "defaultValue": override_entry.get("defaultValue", val),
                                "dimensions": override_entry.get("dimensions") or base_entry["dimensions"],
                            }
                            upsert_parameter_entry(merged_entry, preserve_existing_value=False)
                        else:
                            upsert_parameter_entry(base_entry, preserve_existing_value=False)

        logger.info(f"Parsed structure: {len(data['components'])} components, {len(data['connections'])} connections")
        return data