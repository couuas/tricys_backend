import os
import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any

from tricys_backend.core.config import settings

logger = logging.getLogger(__name__)

class AIService:
    """
    Service to generate AI-enhanced analysis reports using LLMs.
    Ported from tricys_vis analysis_engine.py.
    """
    
    # Configuration (Should ideally be in settings)
    API_KEY = "sk-cf9bb0989c53443a9c35500a7edb2ece" 
    BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    AI_MODEL = "qwen3-max-preview"

    @classmethod
    def generate_enhanced_report(cls, task_work_dir: Path, standard_report_path: Path, analysis_config: Dict[str, Any]) -> Optional[Path]:
        """
        Generates a deep analysis report based on the standard report and configuration.
        Returns the path to the generated AI report.
        """
        try:
            import openai
        except ImportError:
            logger.error("openai package is missing. Cannot generate AI report.")
            return None

        if not standard_report_path.exists():
            logger.warning(f"Standard report not found at {standard_report_path}, skipping AI enhancement.")
            return None

        logger.info(f"Starting AI analysis based on {standard_report_path}")

        # 1. Read Standard Report
        try:
            with open(standard_report_path, 'r', encoding='utf-8') as f:
                standard_report_content = f.read()
        except Exception as e:
            logger.error(f"Error reading standard report: {e}")
            return None

        # 2. Construct Prompt
        # Extract Independent Variable from config
        try:
            # Config structure: sensitivity_analysis -> analysis_cases -> [0] -> independent_variable
            cases = analysis_config.get("sensitivity_analysis", {}).get("analysis_cases", [])
            independent_variable = cases[0].get("independent_variable", "N/A") if cases else "N/A"
        except Exception:
            independent_variable = "Unknown Parameter"

        role_prompt = """**角色：** 你是一名聚变反应堆氚燃料循环领域的专家，擅长从数据报告中解读物理和工程意义，并形成深刻的洞见。

**任务：** 请**仅仅基于**下方提供的**程序生成的分析报告**，撰写一份深度、量化的解读。报告中已经包含了所有必要的数据表格和图表信息。
"""

        analysis_prompt = f"""
**程序生成的初步分析报告：**

{standard_report_content}
"""

        points_prompt = f"""
**分析要点 (必须严格依据上述报告内容作答，禁止使用任何报告外的信息):**

1.  **核心趋势分析 (参考“性能指标总表”):**
    *   独立变量 `{independent_variable}` 的变化，对各个关键性能指标（如 `Startup_Inventory`, `Doubling_Time` 等）产生了怎样的**总体趋势**？请进行量化描述。
    *   哪个因变量对独立变量 `{independent_variable}` 的变化**最为敏感**？哪个**最不敏感**？请通过报告中的数据变化范围或变化率来证明。

2.  **关键指标解读:**
    *   分析 `Startup_Inventory` (启动库存) 的变化趋势，并解释其工程意义。
    *   分析 `Doubling_Time` (倍增时间) 的变化趋势。是否存在一个拐点或阈值，超过该点后 `Doubling_Time` 的变化不再显著或变为无穷大(无法自持)？
    *   分析 `Self_Sufficiency_Time` (自持时间) 的变化，它揭示了什么？

3.  **动态过程分析 (参考“关键动态数据切片：过程数据”):**
    *   观察报告中的“初始阶段”和“结束阶段”的数据，系统行为有何不同？
    *   报告中的“转折点阶段”数据揭示了什么关键的物理过程？（例如，它是否是氚库存由消耗转为净增长的关键时刻？）

4.  **综合结论与工程建议:**
    *   结合所有分析，总结调整 `{independent_variable}` 对整个氚燃料循环系统的综合影响和潜在的**利弊权衡 (Trade-offs)**。
    *   基于这些发现，如果要优化系统性能（例如，寻求更低的启动库存和更短的倍增时间），你对 `{independent_variable}` 的取值或未来的研究方向有何具体建议？
"""
        full_text_prompt = "\n\n".join([role_prompt, analysis_prompt, points_prompt])

        # 3. Call API
        max_retries = 3
        for attempt in range(max_retries):
            try:
                client = openai.OpenAI(api_key=cls.API_KEY, base_url=cls.BASE_URL)
                
                response = client.chat.completions.create(
                    model=cls.AI_MODEL,
                    messages=[{"role": "user", "content": full_text_prompt}],
                    max_tokens=3000,
                )
                analysis_result = response.choices[0].message.content

                # 4. Save Result
                report_filename = "analysis_report_ai.md"
                report_full_path = task_work_dir / report_filename
                
                with open(report_full_path, "w", encoding="utf-8") as f:
                    f.write(analysis_result)
                
                logger.info(f"AI Report saved to {report_full_path}")
                return report_full_path

            except Exception as e:
                logger.error(f"AI API call failed (Attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
        
        return None