"""Feishu Docx client via lark-cli v2 protocol.

v2 protocol notes:
  * ``docs +create`` no longer accepts ``--title`` directly. Title goes into the
    ``--content`` payload wrapped in ``<title>...</title>`` XML.
  * ``docs +create --doc-format xml`` is the entry point; the body is XML.
  * There is no ``docs +delete`` shortcut. Document deletion must go through
    the Feishu native API directly. ``delete_docx`` is a no-op that logs.
"""
from __future__ import annotations

import logging
from typing import Any
from mcp_memory.feishu.runner import LarkCliRunner, LarkCliError

log = logging.getLogger(__name__)


class DocxClient:
    def __init__(self, runner: LarkCliRunner):
        self.runner = runner

    async def create_docx(self, content: str, title: str | None = None) -> str:
        """v2: ``docs +create`` takes ``--content`` with an XML/Markdown body.

        For MVP we wrap the title in a ``<title>`` tag and the body in a single
        ``<p>``. Future enhancements can add block-level writes (paragraphs,
        headings, lists, code blocks).
        """
        title_text = title or "Untitled"
        body = content[:90_000] if content else ""
        body_xml = (
            body
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        full_content = f"<title>{title_text}</title><p>{body_xml}</p>"

        try:
            result = self.runner.run([
                "docs", "+create",
                "--content", full_content,
                "--doc-format", "xml",
            ])
        except LarkCliError:
            return ""

        return self._extract_document_id(result)

    async def delete_docx(self, doc_token: str) -> bool:
        """v2: there is no ``docs +delete`` shortcut.

        The lark-cli v2 protocol exposes ``docs +update`` with ``block_delete``
        for individual blocks, but no shortcut to delete a whole document.
        We log a warning and return False so callers can decide what to do.

        For real deletion, use Feishu native API:
            DELETE /open-apis/docx/v1/documents/:document_id
        """
        log.warning(
            f"lark-cli v2 has no docs +delete shortcut. "
            f"Document {doc_token!r} cannot be deleted via this client. "
            f"Use Feishu native API for deletion."
        )
        return False

    @staticmethod
    def _extract_document_id(result: Any) -> str:
        """Extract document_id from various lark-cli response shapes.

        v2 +create returns:
            {
              "ok": true,
              "data": {
                "document": {"document_id": "..."},
                "permission_grant": {...}
              }
            }
        Native API may return: {"code": 0, "data": {"document": {"document_id": "..."}}}
        """
        if not isinstance(result, dict):
            return ""
        data = result.get("data")
        if isinstance(data, dict):
            doc = data.get("document") if isinstance(data.get("document"), dict) else None
            if doc:
                if doc.get("document_id"):
                    return doc["document_id"]
                if doc.get("doc_id"):
                    return doc["doc_id"]
            if data.get("document_id"):
                return data["document_id"]
            if data.get("doc_id"):
                return data["doc_id"]
        # Some responses have it at top level
        if result.get("document_id"):
            return result["document_id"]
        if result.get("doc_id"):
            return result["doc_id"]
        return ""