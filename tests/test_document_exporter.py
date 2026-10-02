from io import BytesIO

import pytest
from PIL import Image

from backend.services.document_exporter import ExportError, markdown_to_jpg, markdown_to_pdf


SAMPLE_MARKDOWN = """# Sample Project

This is **generated documentation** with a short overview.

## Features

- Upload project
- Analyze source
- Generate documentation

## Data

| Name | Value |
| --- | --- |
| Files | 12 |
| Status | Complete |

> This is an informational note.

```python
print("hello")
```
"""


def test_markdown_to_pdf_returns_pdf_bytes():
    payload = markdown_to_pdf(SAMPLE_MARKDOWN, "Sample Project")

    assert payload.startswith(b"%PDF")
    assert len(payload) > 1000


def test_markdown_to_jpg_returns_valid_jpeg():
    payload = markdown_to_jpg(SAMPLE_MARKDOWN, "Sample Project")

    image = Image.open(BytesIO(payload))
    assert image.format == "JPEG"
    assert image.width == 1600
    assert image.height >= 1000


@pytest.mark.parametrize("renderer", [markdown_to_pdf, markdown_to_jpg])
def test_export_rejects_empty_markdown(renderer):
    with pytest.raises(ExportError):
        renderer("   ", "Empty Project")
