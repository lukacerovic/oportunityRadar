"""Pure identity units (no DB): name normalization, anchor/reference extraction, category vocab.

These functions are load-bearing for the link rules, so they are tested independently of the
engine that calls them.
"""

from __future__ import annotations

from seismo.identity.anchors import Anchor, anchor_from_url, primary_anchor, references
from seismo.identity.normalize import normalize_name
from seismo.identity.vocab import assign_category, categories, theme_for_category, themes

# --- normalize_name ---------------------------------------------------------


def test_normalize_lowercases_and_strips_punctuation_and_emoji() -> None:
    assert normalize_name("vLLM") == "vllm"
    assert normalize_name("🚀 Ollama!") == "ollama"
    assert normalize_name("Deep-Seek") == "deep seek"
    assert normalize_name("deep_seek") == "deep seek"


def test_normalize_drops_packaging_suffixes() -> None:
    assert normalize_name("langchain-official") == "langchain"
    assert normalize_name("foo.py") == "foo"
    assert normalize_name("bar-project") == "bar"
    # A suffix token only drops when it is a *separate* trailing token, not mid-word.
    assert normalize_name("numpy") == "numpy"


def test_normalize_is_idempotent() -> None:
    for name in ["vLLM", "LangChain-official", "🚀 Ollama!", "deep_seek-dev"]:
        once = normalize_name(name)
        assert normalize_name(once) == once


# --- anchor_from_url --------------------------------------------------------


def test_anchor_from_url_parses_each_registry() -> None:
    assert anchor_from_url("https://github.com/vllm-project/vllm") == Anchor(
        "github", "vllm-project/vllm", "project", "vllm-project/vllm"
    )
    assert anchor_from_url("https://arxiv.org/abs/2405.04434v2").key == "arxiv:2405.04434"
    assert anchor_from_url("https://huggingface.co/deepseek-ai/DeepSeek-V2").key == (
        "hf:deepseek-ai/deepseek-v2"
    )
    assert anchor_from_url("https://pypi.org/project/vllm/").key == "pypi:vllm"
    assert anchor_from_url("https://example.com/whatever") is None


# --- primary_anchor ---------------------------------------------------------


def test_primary_anchor_per_source() -> None:
    assert primary_anchor("github", "repo_discovered", {"full_name": "Ollama/Ollama"}).key == (
        "github:ollama/ollama"
    )
    assert primary_anchor("arxiv", "paper_published", {"arxiv_id": "2405.04434"}).key == (
        "arxiv:2405.04434"
    )
    # An HN story anchors to its linked URL's entity, not to itself.
    assert primary_anchor("hn", "story", {"url": "https://github.com/x/y"}).key == "github:x/y"
    assert primary_anchor("hn", "story", {"url": "https://news.example.com"}) is None
    seed_payload = {
        "anchor": {"registry": "github", "native_id": "vllm-project/vllm"},
        "name": "vLLM",
    }
    assert primary_anchor("seed", "seed_anchor", seed_payload).key == "github:vllm-project/vllm"


# --- references (R1–R3 evidence) --------------------------------------------


def test_arxiv_comment_yields_r2_github_reference() -> None:
    payload = {"comment": "Code at https://github.com/deepseek-ai/DeepSeek-V2 and more"}
    refs = references("arxiv", payload)
    assert len(refs) == 1
    assert refs[0].anchor_key == "github:deepseek-ai/deepseek-v2"
    assert refs[0].rule == "R2"


def test_hf_arxiv_tag_yields_r2_reference() -> None:
    refs = references("hf", {"tags": ["arxiv:2405.04434", "text-generation"]})
    assert [r.anchor_key for r in refs] == ["arxiv:2405.04434"]
    assert refs[0].rule == "R2"


def test_github_readme_text_yields_r1_arxiv_reference() -> None:
    # A repo_readme enrichment event carries the body under `text`; its arXiv citation must link
    # the repo to the paper (R1). Without this, GH-Archive-seeded repos are identity islands.
    payload = {"text": "# DeepSeek-V2\n\nSee our paper: https://arxiv.org/abs/2405.04434"}
    refs = references("github", payload)
    assert [r.anchor_key for r in refs] == ["arxiv:2405.04434"]
    assert refs[0].rule == "R1"


def test_pypi_project_urls_yield_r3_github_reference() -> None:
    payload = {"project_urls": {"Repository": "https://github.com/vllm-project/vllm"}}
    refs = references("pypi", payload)
    assert refs[0].anchor_key == "github:vllm-project/vllm"
    assert refs[0].rule == "R3"


# --- vocab ------------------------------------------------------------------


def test_vocab_loads_and_theme_mapping_is_valid() -> None:
    cats = categories()
    assert len(cats) >= 25
    known = set(themes())
    assert all(c.theme in known for c in cats)


def test_assign_category_keyword_priority() -> None:
    assert (
        assign_category("A high-throughput LLM serving and inference engine") == "inference-runtime"
    )
    assert assign_category("A framework for building autonomous AI agents") == "agent-framework"
    assert assign_category("just some unrelated text about gardening") == "uncategorized"
    # word-boundary: 'rag' must not fire on 'storage'
    assert assign_category("distributed storage system") != "rag-framework"


def test_theme_for_category_defaults() -> None:
    assert theme_for_category("inference-runtime") == "efficient inference"
    assert theme_for_category("does-not-exist") == "uncategorized"
