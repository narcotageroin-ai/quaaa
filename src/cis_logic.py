from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import re

CIS_BLOCK_RE = re.compile(r"\[CIS\].*?\[/CIS\]", re.S)

def _get_attr_bool(entity: Dict[str, Any], attr_name: str) -> Optional[bool]:
    attrs = entity.get("attributes") or []
    for a in attrs:
        if str(a.get("name", "")).strip() == attr_name.strip():
            v = a.get("value")
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes", "да")
            if isinstance(v, (int, float)):
                return bool(v)
    return None

def replace_cis_block(description: str, codes: List[str]) -> str:
    description = description or ""
    body = "\n".join(codes)
    block = f"[CIS]\n{body}\n[/CIS]"
    if CIS_BLOCK_RE.search(description):
        return CIS_BLOCK_RE.sub(block, description).strip()
    return (description.strip() + "\n\n" + block).strip() if description.strip() else block

def normalize_codes(raw_text: str) -> Tuple[List[str], List[str]]:
    lines = [ln.strip() for ln in (raw_text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    seen = set()
    uniq = []
    dups = []
    for ln in lines:
        if ln in seen:
            dups.append(ln)
        else:
            seen.add(ln)
            uniq.append(ln)
    return uniq, dups

def soft_validate_datamatrix(code: str) -> List[str]:
    warnings = []
    c = code.strip()
    if not c.startswith("01"):
        warnings.append("не начинается с '01'")
    if "21" not in c:
        warnings.append("не содержит '21' (серийный номер)")
    if len(c) < 25:
        warnings.append("слишком короткий для типичного DataMatrix GS1")
    return warnings
