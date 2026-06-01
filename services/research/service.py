# services/research/service.py
"""Research service — deep research with LLM-in-the-loop."""

from dataclasses import dataclass, field
from typing import List, Optional, Callable

from .research_handler import ResearchHandler


@dataclass
class ResearchSource:
    """A source found during research."""
    url: str
    title: str
    snippet: str


@dataclass
class ResearchResult:
    """Result of a deep research query."""
    query: str
    summary: str
    sources: List[ResearchSource] = field(default_factory=list)
    duration_seconds: float = 0.0


class ResearchService:
    """
    Deep research service.

    Usage:
        service = ResearchService()
        result = await service.research("quantum computing advances 2024")
        print(result.summary)
    """

    def __init__(self):
        self.handler = ResearchHandler()
        self._active: dict = {}

    async def research(
        self,
        topic: str,
        llm_endpoint: str,
        llm_model: str,
        max_time: int = 300,
        on_progress: Optional[Callable[[dict], None]] = None,
    ) -> ResearchResult:
        """
        Perform deep research on a topic.

        Args:
            topic: Research topic/question
            llm_endpoint: LLM API endpoint
            llm_model: Model to use
            max_time: Maximum time in seconds
            on_progress: Optional progress callback

        Returns:
            ResearchResult with findings
        """
        import time
        start = time.time()

        # call_research_service returns the formatted markdown report (a str),
        # and stashes the live DeepResearcher in the entry we pass so we can pull
        # the per-source findings back out for the structured result.
        entry: dict = {}
        report = await self.handler.call_research_service(
            topic,
            llm_endpoint,
            llm_model,
            max_time=max_time,
            progress_callback=on_progress,
            _task_entry=entry,
        )

        duration = time.time() - start

        researcher = entry.get("researcher")
        raw_findings = (
            self.handler._extract_raw_findings(researcher.findings)
            if researcher and researcher.findings
            else []
        )
        sources = [
            ResearchSource(
                url=f.get("url", ""),
                title=f.get("title", ""),
                snippet=f.get("summary", ""),
            )
            for f in raw_findings
        ]

        return ResearchResult(
            query=topic,
            summary=report,
            sources=sources,
            duration_seconds=duration,
        )

    def start_background(
        self,
        session_id: str,
        topic: str,
        llm_endpoint: str,
        llm_model: str,
        max_time: int = 300,
    ) -> dict:
        """Start research in background. Returns task info."""
        return self.handler.start_research(
            session_id, topic, llm_endpoint, llm_model, max_time
        )

    def get_status(self, session_id: str) -> Optional[dict]:
        """Get status of background research."""
        return self.handler.get_status(session_id)

    def cancel(self, session_id: str) -> bool:
        """Cancel background research."""
        return self.handler.cancel_research(session_id)
