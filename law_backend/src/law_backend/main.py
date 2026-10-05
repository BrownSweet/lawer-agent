"""Explicit bounded CrewAI Flow; business checkpoints live in MySQL."""

from crewai.flow import Flow, listen, start
from pydantic import BaseModel, Field

from .contracts import Draft, Finding, Review, verify_draft


class AnalysisState(BaseModel):
    context: dict = Field(default_factory=dict)
    intake: dict = Field(default_factory=dict)
    research: dict = Field(default_factory=dict)
    draft: dict = Field(default_factory=dict)
    review: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)


class LegalFlow(Flow[AnalysisState]):
    def __init__(self, *, executor, checkpoint, check_cancel, context):
        super().__init__()
        self.executor = executor
        self.checkpoint = checkpoint
        self.check_cancel = check_cancel
        self.state.context = context

    def execute(self, stage, payload, schema):
        self.check_cancel()
        self.checkpoint(stage, None, {})
        result, usage = self.executor(stage, payload, schema)
        self.check_cancel()
        self.checkpoint(stage, result, usage)
        return result

    @start()
    def intake(self):
        self.state.intake = self.execute("intake", self.state.context, Finding)

    @listen(intake)
    def research(self):
        self.state.research = self.execute(
            "research", {**self.state.context, "intake": self.state.intake}, Finding
        )

    @listen(research)
    def draft(self):
        self.state.draft = self.execute(
            "draft",
            {**self.state.context, "intake": self.state.intake, "research": self.state.research},
            Draft,
        )

    @listen(draft)
    def review(self):
        claims = [c for section in self.state.draft["sections"] for c in section["claims"]]
        self.state.review = self.execute(
            "review",
            {**self.state.context, "draft": self.state.draft, "indexed_claims": list(enumerate(claims))},
            Review,
        )

    @listen(review)
    def validate(self):
        self.check_cancel()
        self.state.result = verify_draft(
            Draft.model_validate(self.state.draft),
            Review.model_validate(self.state.review),
            self.state.context["evidence"],
        )
        self.state.result["evidence"] = self.state.context["evidence"]
        self.state.result["coverage"] = self.state.context["coverage"]
        return self.state.result
