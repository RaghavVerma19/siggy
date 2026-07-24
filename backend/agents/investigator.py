import os
import json
import asyncio
from datetime import datetime, timedelta
from groq import Groq
from dotenv import load_dotenv

from telemetry.signoz_mcp import get_telemetry_provider
from telemetry.summarizer import summarize_telemetry
from utils.fallbacks import infer_service

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class InvestigatorAgent:
    def __init__(self):
        self.telemetry = get_telemetry_provider()

    async def investigate(self, query: str) -> dict:
        now = datetime.utcnow()
        start_time = (now - timedelta(hours=1)).isoformat() + "Z"
        end_time = now.isoformat() + "Z"

        try:
            services = await self.telemetry.list_services(start_time, end_time)
        except Exception:
            services = []
        relevant_service = self._identify_service(query, services)

        logs_task = self.telemetry.search_logs(
            service=relevant_service,
            query="level:error OR level:warn OR timeout OR exception OR error",
            limit=30,
            start_time=start_time,
            end_time=end_time,
        )
        traces_task = self.telemetry.search_traces(
            service=relevant_service,
            min_duration_ms=1000,
            limit=20,
            start_time=start_time,
            end_time=end_time,
        )
        latency_task = self.telemetry.query_metrics(
            service=relevant_service,
            metric_name="http_request_duration_milliseconds",
            aggregation="p99",
            start_time=start_time,
            end_time=end_time,
        )
        error_task = self.telemetry.query_metrics(
            service=relevant_service,
            metric_name="http_requests_total",
            aggregation="rate",
            start_time=start_time,
            end_time=end_time,
        )

        results = await asyncio.gather(
            logs_task, traces_task, latency_task, error_task,
            return_exceptions=True,
        )

        logs = results[0] if not isinstance(results[0], Exception) else []
        traces = results[1] if not isinstance(results[1], Exception) else []
        latency_metric = results[2] if not isinstance(results[2], Exception) else {}
        error_metric = results[3] if not isinstance(results[3], Exception) else {}

        raw_data = {
            "query": query,
            "service": relevant_service,
            "time_range": {"start": start_time, "end": end_time},
            "logs": logs,
            "traces": traces,
            "latency_metric": latency_metric,
            "error_metric": error_metric,
        }

        summary = summarize_telemetry(raw_data)
        return summary

    def _identify_service(self, query: str, services: list[dict]) -> str:
        query_lower = query.lower()

        for svc in services:
            svc_name = svc.get("serviceName", "").lower()
            if svc_name in query_lower or query_lower in svc_name:
                return svc.get("serviceName", "unknown")

        if not services:
            return infer_service(query, "unknown")

        service_names = [s.get("serviceName", "unknown") for s in services]
        heuristic = infer_service(query, "")
        if heuristic and any(heuristic == svc.lower() for svc in service_names):
            return heuristic
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are a service classifier. Return ONLY the service name."},
                    {"role": "user", "content": f"User query: '{query}'\nAvailable services: {service_names}\nWhich service is the user talking about? Return ONLY the service name."},
                ],
                temperature=0,
            )
            return response.choices[0].message.content.strip().strip('"').strip("'")
        except Exception:
            return service_names[0] if service_names else "unknown"
