"""The deliberately missing capability that an engineering proposal may add."""


def export_pdf(project_name: str, rows: list[str]) -> bytes:
    raise NotImplementedError("PDF export needs an engineer-reviewed code change")
