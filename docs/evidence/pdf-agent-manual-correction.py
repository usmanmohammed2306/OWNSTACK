"""Agent-authored manual-path correction, not a successful Nemotron output.

Bounded one-page Latin-1 export for the synthetic sample. Long reports and Unicode
layout require further engineering. This source is checked in the verifier only.
"""
from io import BytesIO


def export_pdf(project_name: str, rows: list[str]) -> bytes:
    def escape(value: str) -> bytes:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace")

    commands = [b"BT /F1 12 Tf 50 770 Td"]
    for index, line in enumerate([project_name, *rows]):
        if index:
            commands.append(b"0 -18 Td")
        commands.append(b"(" + escape(line) + b") Tj")
    commands.append(b"ET")
    stream = b"\n".join(commands)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    startxref = output.tell()
    output.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n".encode())
    return output.getvalue()
