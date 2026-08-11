import logging
from typing import Any, Dict, List

from OMPython import OMCSessionZMQ

logger = logging.getLogger(__name__)

class SchemaService:
    @staticmethod
    def _extract_schema_from_omc(
        omc: Any, package_name: str, target_classes: List[str] = None
    ) -> Dict[str, Any]:
        """
        Extracts the schema from an active OMC session for the specified classes in a package.
        """
        schema = {}

        classes = omc.sendExpression(f"getClassNames({package_name})", parsed=True)
        if not classes:
            # Fallback: maybe package_name is a single model
            elements_raw = omc.sendExpression(f"getElements({package_name})", parsed=False)
            if elements_raw:
                classes = [package_name]
                package_name = ""
            else:
                logger.warning(f"No classes found in package '{package_name}'.")
                return schema

        for cls in classes:
            if target_classes is not None and cls not in target_classes:
                continue

            full_cls_name = f"{package_name}.{cls}" if package_name else cls
            elements_raw = omc.sendExpression(f"getElements({full_cls_name})", parsed=False)

            cls_schema = {"parameters": {}, "variables": {}, "connectors": {}}

            if not elements_raw:
                continue

            elements_strs = elements_raw.split("}, {")
            for el_str in elements_strs:
                el_str = el_str.strip("{").strip("}")
                parts = []
                in_string = False
                in_brace = 0
                current_part = ""
                for char in el_str:
                    if char == '"':
                        in_string = not in_string
                        current_part += char
                    elif char == "{" and not in_string:
                        in_brace += 1
                        current_part += char
                    elif char == "}" and not in_string:
                        in_brace -= 1
                        current_part += char
                    elif char == "," and not in_string and in_brace == 0:
                        parts.append(current_part.strip())
                        current_part = ""
                    else:
                        current_part += char
                parts.append(current_part.strip())

                if len(parts) >= 11:
                    el_type = parts[2]
                    name = parts[3]
                    description = parts[4].strip('"')
                    variability = parts[10].strip('"')  # e.g. "parameter"

                    # Dimension is the 15th element (index 14) typically, or the last part
                    dimension_part = parts[-1] if parts[-1].startswith("{") else "{}"
                    dimension = dimension_part.strip("{}").strip()
                    if not dimension:
                        dimension = None
                    else:
                        dimension = [d.strip() for d in dimension.split(",")]

                    # Use raw omc command for value
                    val_raw = omc.sendExpression(
                        f"getComponentModifierValue({full_cls_name}, {name})", parsed=False
                    )
                    val = val_raw.strip() if val_raw else None
                    if val == '""':
                        val = None

                    el_info = {
                        "type": el_type,
                        "dimension": dimension,
                        "description": description,
                        "value": val,
                    }

                    if "Modelica.Blocks.Interfaces" in el_type:
                        cls_schema["connectors"][name] = el_info
                    elif variability == "parameter" or variability == "constant":
                        cls_schema["parameters"][name] = el_info
                    else:
                        cls_schema["variables"][name] = el_info

            schema[cls] = cls_schema

        return schema

    @staticmethod
    def extract_schema(mo_file_path: str, package_name: str) -> Dict[str, Any]:
        """
        Dynamically extracts a schema from a Modelica file using OMPython.
        """
        logger.info(f"Starting OMC Session to extract schema from {mo_file_path} (package: {package_name})")
        omc = OMCSessionZMQ()
        try:
            # Use forward slashes for cross-platform compatibility
            normalized_path = mo_file_path.replace("\\", "/")
            res = omc.sendExpression(f'loadFile("{normalized_path}")')
            if str(res).strip().lower() != "true":
                logger.warning(f"OMC loadFile returned {res} for {normalized_path}")

            schema = SchemaService._extract_schema_from_omc(omc, package_name)
            logger.info("Schema extraction successful.")
            return schema
        except Exception as e:
            logger.error(f"Failed to extract schema via OMC: {e}")
            return {}
        finally:
            try:
                omc.sendExpression("quit()")
            except Exception:
                pass
