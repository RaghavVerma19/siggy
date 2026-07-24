from abc import ABC, abstractmethod


class TelemetryProvider(ABC):
    """Abstract telemetry provider. Swappable backends: SigNoz, Datadog, New Relic, PagerDuty."""

    @abstractmethod
    async def list_services(
        self,
        start_time: str,
        end_time: str,
    ) -> list[dict]:
        pass

    @abstractmethod
    async def search_logs(
        self,
        service: str,
        query: str,
        limit: int = 50,
        start_time: str = "",
        end_time: str = "",
    ) -> list[dict]:
        pass

    @abstractmethod
    async def search_traces(
        self,
        service: str,
        query: str = "",
        min_duration_ms: int = 0,
        limit: int = 20,
        start_time: str = "",
        end_time: str = "",
    ) -> list[dict]:
        pass

    @abstractmethod
    async def query_metrics(
        self,
        service: str,
        metric_name: str,
        aggregation: str = "avg",
        start_time: str = "",
        end_time: str = "",
    ) -> dict:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass
