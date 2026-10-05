from typing import Literal

from pydantic import BaseModel, Field


class Claim(BaseModel):
    text: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list, description="仅使用输入提供的 P:页ID 或 S:来源ID")
    kind: Literal["fact", "inference", "legal"] = "inference"


class Finding(BaseModel):
    title: str
    summary: str
    claims: list[Claim] = Field(default_factory=list)
    timeline: list[dict[str, str]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class Draft(BaseModel):
    title: str
    summary: str
    sections: list[Finding]
    next_steps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ReviewItem(BaseModel):
    claim_index: int = Field(ge=0, description="草稿 claims 扁平列表的下标")
    verdict: Literal["supported", "contradicted", "insufficient"]
    reason: str


class Review(BaseModel):
    items: list[ReviewItem]
    summary: str
    issues: list[str] = Field(default_factory=list)


def verify_draft(draft: Draft, review: Review, evidence: dict):
    """Existence, support and legal validity remain independent dimensions."""
    claims = [c for section in draft.sections for c in section.claims]
    review_map = {}
    duplicates = set()
    for item in review.items:
        if item.claim_index in review_map:
            duplicates.add(item.claim_index)
        review_map[item.claim_index] = item
    rows = []
    for index, claim in enumerate(claims):
        missing = [ref for ref in claim.citations if ref not in evidence]
        item = review_map.get(index)
        association = "linked" if claim.citations and not missing else "unverified"
        support = item.verdict if item and index not in duplicates else "insufficient"
        if missing or not claim.citations:
            support = "insufficient"
        legal_unverified = claim.kind == "legal"  # LLM/source labels never certify current validity.
        rows.append(
            {
                **claim.model_dump(),
                "index": index,
                "association": association,
                "support": support,
                "validity": "needs_review" if legal_unverified else "not_applicable",
                "reason": item.reason if item else "复核结果缺少此项",
                "missing_citations": missing,
            }
        )
    issues = list(review.issues)
    if duplicates or any(i >= len(claims) for i in review_map):
        issues.append("复核项重复或超出草稿范围")
    needs_review = (
        not rows
        or bool(issues)
        or any(r["support"] != "supported" or r["validity"] == "needs_review" for r in rows)
    )
    return {
        "claims": rows,
        "needs_review": needs_review,
        "issues": issues,
        "review_summary": review.summary,
        "draft": draft.model_dump(),
    }
