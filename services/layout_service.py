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

        # --- 1. Locate Cycle Model Block (Main System) ---
        # Match model Cycle ... end Cycle;
        cycle_block_pattern = re.compile(r"model\s+Cycle(.*?)end\s+Cycle;", re.DOTALL | re.IGNORECASE)
        match_block = cycle_block_pattern.search(content)
        
        cycle_content = match_block.group(1) if match_block else content

        # Map: Type -> Instance Name (e.g. "Plasma" -> "plasma")
        instance_map = {} 

        # --- 2. Parse Components [ROBUST STRATEGY] ---
        # We process line by line or statement by statement to find "Type Name ...;"
        # This is more robust than a single complex regex which might fail on formatting nuances.

        # Regex to capture basic declaration: Type Name ... ;
        # Excludes "connect(...)", "equation", "annotation", "parameter"
        # We assume standard Modelica formatting where declaration ends with ; 
        # but might have annotation before the ;
        
        # Simple pattern: Start of line or space, Type, space, Name, optional stuff, ;
        # We need to capture the full statement to search for annotation inside it.
        statement_pattern = re.compile(
            r"^\s*([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)(.*?);", 
            re.MULTILINE | re.DOTALL
        )
        
        # Origin pattern to search WITHIN the statement
        origin_pattern = re.compile(r"origin\s*=\s*\{([-\d\.]+)\s*,\s*([-\d\.]+)\}")

        keywords = {"Modelica", "import", "parameter", "constant", 
                   "Real", "Integer", "Boolean", "String", 
                   "equation", "algorithm", "initial", "protected", "public",
                   "connect", "annotation"}

        components_found = []
        
        for match in statement_pattern.finditer(cycle_content):
            comp_type = match.group(1)
            comp_name = match.group(2)
            rest_of_line = match.group(3)
            
            if comp_type in keywords:
                continue
                
            # Heuristic: If type starts with lowercase, it might be a keyword we missed or a function
            # Conventionally types are Capitalized. But we'll trust the exclusion list.

            # Basic position defaults
            x, y = 0.0, 0.0
            
            # Check for origin in the statement body
            origin_match = origin_pattern.search(rest_of_line)
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
            
            instance_map[comp_type] = comp_name

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
        model_def_pattern = re.compile(r"(model\s+([a-zA-Z0-9_]+)(.*?)end\s+\2;)", re.DOTALL)
        
        for match in model_def_pattern.finditer(content):
            full_code = match.group(1)
            model_type = match.group(2)
            model_body = match.group(3)
            
            if model_type in instance_map:
                instance_name = instance_map[model_type]
                
                # Save source code
                data["source_codes"][instance_name] = full_code.strip()
                
                # Extract parameters: parameter Real fb = 0.05 "Description";
                # Improved regex to stop at the start of the description string (starting with ")
                # Capture Group 2 is the value. We use non-greedy matching until a space followed by a quote OR semicolon
                param_pattern = re.compile(
                    r"parameter\s+\w+\s+"                # parameter Type
                    r"([a-zA-Z0-9_]+)"                   # Name (Group 1)
                    r"(?:\[.*?\])?"                      # Optional array dims
                    r"\s*=\s*"                           # = 
                    r"([^;]*?)"                          # Value (Group 2) - extract everything first, refine later
                    r"\s*(?:\"(.*?)\"\s*)?;"             # Optional Description "..." and ending ;
                )
                
                for p_match in param_pattern.finditer(model_body):
                    p_name = p_match.group(1)
                    raw_val = p_match.group(2).strip()
                    
                    # If raw_val contains the description (because regex didn't split well), fix it
                    # The previous regex `([^;]+?)` combined with `(?:\"...\" )?;` relies on the quote being present.
                    # If value is `24 "desc"`, extracting `24` needs care.
                    
                    # Split by first quote if exists
                    if '"' in raw_val:
                        p_val_str = raw_val.split('"')[0].strip()
                    else:
                        p_val_str = raw_val
                        
                    try:
                        # Handle arrays {1, 2} -> [1, 2]
                        if p_val_str.startswith('{') and p_val_str.endswith('}'):
                            py_list_str = p_val_str.replace('{', '[').replace('}', ']')
                            val = eval(py_list_str)
                        else:
                            val = float(p_val_str)
                    except:
                        val = p_val_str
                    
                    key = f"{instance_name}.{p_name}"
                    
                    # Store as structured object
                    data["parameters"].append({
                        "name": key,
                        "type": "Real", # Regex matched parameter Real ...
                        "value": val, # Initialize current value with default
                        "defaultValue": val, # The raw valid value
                        "comment": p_match.group(3).strip() if p_match.group(3) else "",
                        "dimensions": "()" # Default scalar, could parse array dims better later
                    })

        logger.info(f"Parsed structure: {len(data['components'])} components, {len(data['connections'])} connections")
        return data