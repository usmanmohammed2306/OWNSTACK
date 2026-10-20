"""External, bounded oracle for OwnStack's deliberately narrow PDF export contract.

Not a general PDF parser or a security certification. Candidate code never imports
this module in its execution process. The trusted parent judges returned bytes.
"""
import base64
import hashlib
import json
import re
import secrets

ORACLE_VERSION = "pdf-external-v1"
MAX_PDF_BYTES = 65_536
MAX_OUTPUT_BYTES = 786_432
CASE_IDS = {"atlas", "escaped", "empty", "latin1", "many", "nonce", "separate_scope"}


def cases() -> list[dict]:
    nonce = secrets.token_hex(8)
    return [
        {"id": "atlas", "project": "Project Atlas", "rows": ["Design complete", "Review pending"]},
        {"id": "escaped", "project": "Atlas (private)", "rows": [r"A\B", "Budget (approved)"]},
        {"id": "empty", "project": "Empty", "rows": []},
        {"id": "latin1", "project": "Café", "rows": ["Résumé", "Unicode \u2603"]},
        {"id": "many", "project": "Many rows", "rows": [f"Task {i}" for i in range(22)]},
        {"id": "nonce", "project": f"Atlas-{nonce}", "rows": [f"Only supplied data {nonce}"]},
        {"id": "separate_scope", "project": "Independent fixture", "rows": ["No implicit tenant data"]},
    ]


def _literal(value: bytes) -> str:
    result = bytearray()
    i = 0
    while i < len(value):
        char = value[i]
        if char == 92:
            i += 1
            if i == len(value) or value[i] not in b"\\()":
                raise ValueError("Unsupported PDF escape")
            result.append(value[i])
        elif char in b"()":
            raise ValueError("Unescaped PDF delimiter")
        else:
            result.append(char)
        i += 1
    return result.decode("cp1252")


def validate_pdf(pdf: bytes, case: dict) -> None:
    """Check xref, object graph, stream length and exact visible text independently."""
    if len(pdf) > MAX_PDF_BYTES or not pdf.startswith(b"%PDF-1.4\n"):
        raise ValueError("Expected bounded PDF-1.4 output")
    trailer = re.search(rb"trailer\s*<<\s*/Size\s+6\s+/Root\s+1 0 R\s*>>\s*startxref\s+(\d+)\s+%%EOF\s*\Z", pdf)
    if not trailer or pdf.count(b"%%EOF") != 1:
        raise ValueError("Invalid trailer or EOF")
    offset = int(trailer[1])
    xref = re.fullmatch(rb"xref\s+0 6\s+0000000000 65535 f\s+((?:\d{10} 00000 n\s+){5})", pdf[offset:trailer.start()])
    if not xref:
        raise ValueError("Invalid cross-reference table")
    offsets = [int(n) for n in re.findall(rb"(\d{10}) 00000 n", xref[1])]
    if offsets != sorted(set(offsets)) or offsets[0] != len(b"%PDF-1.4\n"):
        raise ValueError("Invalid object offsets")
    objects = []
    for number, (start, end) in enumerate(zip(offsets, offsets[1:] + [offset]), 1):
        match = re.fullmatch(str(number).encode() + rb" 0 obj\s*\n(.*?)\nendobj\s*\n", pdf[start:end], re.S)
        if not match:
            raise ValueError("Object did not match its cross-reference offset")
        objects.append(match[1])
    # A small explicit output format keeps the oracle independent and reviewable.
    expected = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    normalize = lambda value: b" ".join(value.split())
    if [normalize(obj) for obj in objects[:4]] != [normalize(obj) for obj in expected]:
        raise ValueError("Unsupported object graph or unexpected PDF behavior")
    stream = re.fullmatch(rb"<<\s*/Length\s+(\d+)\s*>>\s*\nstream\n(.*)\nendstream", objects[4], re.S)
    if not stream or len(stream[2]) != int(stream[1]):
        raise ValueError("Invalid content stream length")
    commands = stream[2].splitlines()
    if not commands or commands[0] != b"BT /F1 12 Tf 50 770 Td" or commands[-1] != b"ET":
        raise ValueError("Unsupported text stream")
    actual = []
    for index, command in enumerate(commands[1:-1]):
        if index % 2:
            if command != b"0 -18 Td":
                raise ValueError("Unexpected text positioning")
        else:
            match = re.fullmatch(rb"\((.*)\) Tj", command)
            if not match:
                raise ValueError("Unexpected text operator")
            actual.append(_literal(match[1]))
    expected_text = [line.encode("cp1252", errors="replace").decode("cp1252") for line in [case["project"], *case["rows"]]]
    if actual != expected_text or len(commands) != 2 * len(expected_text) + 1:
        raise ValueError("Export does not contain exactly the supplied scope's text")


def judge(stdout: bytes, case_set: list[dict], *, exit_code: int | None, failure: str = "") -> dict:
    verdicts = []
    try:
        if failure or exit_code != 0 or len(stdout) > MAX_OUTPUT_BYTES:
            raise ValueError(failure or "Candidate failed or exceeded output bounds")
        outputs = json.loads(stdout)
        if not isinstance(outputs, list) or len(outputs) != len(case_set):
            raise ValueError("Missing or extra exported documents")
        for case, encoded in zip(case_set, outputs):
            try:
                if not isinstance(encoded, str) or len(encoded) > 4 * (MAX_PDF_BYTES // 3 + 1):
                    raise ValueError("Export exceeds bounds")
                pdf = base64.b64decode(encoded, validate=True)
                validate_pdf(pdf, case)
                verdicts.append({"id": case["id"], "passed": True, "pdf_sha256": hashlib.sha256(pdf).hexdigest()})
            except (ValueError, TypeError) as error:
                verdicts.append({"id": case["id"], "passed": False, "reason": str(error)})
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        failure = str(error)
    return {"oracle_version": ORACLE_VERSION, "checks_expected": len(case_set),
            "checks_completed": len(verdicts), "cases": verdicts,
            "passed": not failure and len(verdicts) == len(case_set) and all(v["passed"] for v in verdicts),
            "oracle_error": failure}


def is_external_pass(result: dict) -> bool:
    expected = result.get("checks_expected")
    verdicts = result.get("cases")
    return (result.get("passed") is True and result.get("oracle_version") == ORACLE_VERSION
            and not result.get("oracle_error") and result.get("exit_code", 0) == 0
            and type(expected) is int and expected == len(CASE_IDS)
            and result.get("checks_completed") == expected
            and isinstance(verdicts, list) and len(verdicts) == expected
            and all(isinstance(v, dict) and isinstance(v.get("id"), str) for v in verdicts)
            and {v["id"] for v in verdicts} == CASE_IDS
            and all(isinstance(v, dict) and v.get("passed") is True
                    and isinstance(v.get("pdf_sha256"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", v["pdf_sha256"]) for v in verdicts))
