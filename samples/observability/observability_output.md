# Observability Log Summary

**Date:** 2026-03-31 09:38:28  
**Total runtime:** 34.4s  

This file contains representative log extracts from a single run of the observability news-agent sample.  Each section shows how the OpenTelemetry + Azure Monitor setup produces telemetry at different layers of the stack.

---

## OpenTelemetry / Tracing

_These logs come from the OpenTelemetry SDK — span creation, context propagation, and export.  They appear because we called `configure_otel_providers()` which sets up a TracerProvider with the Azure Monitor exporter._

**10 log entries captured** (showing up to 15 representative samples)

```
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://westus-0.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '1261'
    'Accept': 'application/json'
    'x-ms-client-re...
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://eastus-8.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '1979'
    'Accept': 'application/json'
    'x-ms-client-re...
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://eastus-8.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '5286'
    'Accept': 'application/json'
    'x-ms-client-re...
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://eastus-8.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '5124'
    'Accept': 'application/json'
    'x-ms-client-re...
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://eastus-8.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '5535'
    'Accept': 'application/json'
    'x-ms-client-re...
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://eastus-8.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '14707'
    'Accept': 'application/json'
    'x-ms-client-r...
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://eastus-8.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '2364'
    'Accept': 'application/json'
    'x-ms-client-re...
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://eastus-8.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '3660'
    'Accept': 'application/json'
    'x-ms-client-re...
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://eastus-8.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '4723'
    'Accept': 'application/json'
    'x-ms-client-re...
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'https://eastus-8.in.applicationinsights.azure.com//v2.1/track'
Request method: 'POST'
Request headers:
    'Content-Type': 'application/json'
    'Content-Length': '18801'
    'Accept': 'application/json'
    'x-ms-client-r...
```

---

## Azure Monitor Export

_The Azure Monitor exporter batches finished spans and metrics and sends them to Application Insights.  These logs show the export pipeline in action._

**9 log entries captured** (showing up to 15 representative samples)

```
[INFO   ] azure.monitor.opentelemetry.exporter.export._base: Transmission succeeded: Item received: 3. Items accepted: 3
[INFO   ] azure.monitor.opentelemetry.exporter.export._base: Transmission succeeded: Item received: 6. Items accepted: 6
[INFO   ] azure.monitor.opentelemetry.exporter.export._base: Transmission succeeded: Item received: 4. Items accepted: 4
[INFO   ] azure.monitor.opentelemetry.exporter.export._base: Transmission succeeded: Item received: 10. Items accepted: 10
```

---

## Agent Framework

_The agent-framework library logs every LLM call, tool invocation, and message exchange.  With `enable_sensitive_data=True` the full message content is included, which is useful during development._

**86 log entries captured** (showing up to 15 representative samples)

```
[INFO   ] agent_framework: {'role': 'system', 'parts': [{'type': 'text', 'content': 'You are a helpful news assistant that uses the provided tools to fetch and summarize Hacker News stories. When asked about Hacker News, first fetch relevant story IDs, then retrieve their details and provide conc...
[INFO   ] agent_framework: {'role': 'user', 'parts': [{'type': 'text', 'content': 'Give me a brief summary of the current top 5 Hacker News stories.'}]}
[INFO   ] agent_framework: {'role': 'assistant', 'parts': [{'type': 'tool_call', 'id': 'call_nTUovttWj3WoB0f6fb2rh3Tl', 'name': 'get_hn_ids_observed', 'arguments': '{"list_type":"top","limit":5}'}], 'finish_reason': 'tool_call'}
[DEBUG  ] agent_framework: _try_execute_function_calls: tool_map keys=['get_hn_ids_observed', 'get_hn_story_observed'], approval_tools=[]
[DEBUG  ] agent_framework: Checking function call: type=function_call, name=get_hn_ids_observed, in approval_tools=False
[INFO   ] agent_framework: Function name: get_hn_ids_observed
[DEBUG  ] agent_framework: Function arguments: {'list_type': 'top', 'limit': 5}
[INFO   ] agent_framework: Function get_hn_ids_observed succeeded.
[INFO   ] agent_framework: {'role': 'user', 'parts': [{'type': 'text', 'content': 'Now, focus on any stories related to AI or machine learning.'}]}
[INFO   ] agent_framework: {'role': 'assistant', 'parts': [{'type': 'text', 'content': 'Among the current top 5 Hacker News stories, the ones related to AI or machine learning are:\n\n1. "Ollama is now powered by MLX on Apple Silicon in preview" - Ollama is now running on MLX, a machine learning ...
[INFO   ] agent_framework: {'role': 'user', 'parts': [{'type': 'text', 'content': 'Remind me which story had the highest score.'}]}
[INFO   ] agent_framework: {'role': 'assistant', 'parts': [{'type': 'text', 'content': 'The story with the highest score is "Axios compromised on NPM – Malicious versions drop remote access trojan" with a score of 571.'}], 'finish_reason': 'stop'}
[INFO   ] agent_framework: {'role': 'assistant', 'parts': [{'type': 'text', 'content': 'The story with the highest score is "Axios compromised on NPM – Malicious versions drop remote access trojan" with a score of 571.'}]}
  ... (71 more entries)
```

---

## Azure Identity / Auth

_When using RBAC (no API key), DefaultAzureCredential tries multiple credential sources.  These logs show which credential succeeded and token acquisition._

**25 log entries captured** (showing up to 15 representative samples)

```
[INFO   ] azure.identity._credentials.environment: No environment configuration found.
[INFO   ] azure.identity._credentials.managed_identity: ManagedIdentityCredential will use IMDS
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Response status: 200
Response headers:
    'Transfer-Encoding': 'chunked'
    'Content-Type': 'application/json; charset=utf-8'
    'Server': 'Microsoft-HTTPAPI/2.0'
    'Strict-Transport-Security': 'REDACTED'
    'X-Content-Type-Options...
[DEBUG  ] azure.identity._internal.decorators: EnvironmentCredential.get_token_info failed: EnvironmentCredential authentication unavailable. Environment variables are not fully configured.
Visit https://aka.ms/azsdk/python/identity/environmentcredential/troubleshoot to troubleshoot this issue.
[INFO   ] azure.core.pipeline.policies.http_logging_policy: Request URL: 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=REDACTED&resource=REDACTED'
Request method: 'GET'
Request headers:
    'User-Agent': 'azsdk-python-identity/1.25.3 Python/3.14.3 (Windows-11-10.0.26200-SP0)'...
[DEBUG  ] azure.identity._internal.msal_managed_identity_client: ImdsCredential.get_token_info failed: ManagedIdentityCredential authentication unavailable, no response from the IMDS endpoint.
  ... (10 more entries)
```

---

## HTTP Requests (httpx)

_The httpx library logs each outgoing HTTP request.  This covers both the Hacker News API calls (tool execution) and the Azure OpenAI chat completion requests._

**11 log entries captured** (showing up to 15 representative samples)

```
[INFO   ] httpx: HTTP Request: POST https://vw-te-openai.openai.azure.com/openai/deployments/gpt-4.1-mini/chat/completions?api-version=2024-10-21 "HTTP/1.1 200 OK"
[INFO   ] httpx: HTTP Request: GET https://hacker-news.firebaseio.com/v0/topstories.json?print=pretty "HTTP/1.1 200 OK"
[INFO   ] httpx: HTTP Request: GET https://hacker-news.firebaseio.com/v0/item/47582220.json?print=pretty "HTTP/1.1 200 OK"
[INFO   ] httpx: HTTP Request: GET https://hacker-news.firebaseio.com/v0/item/47582482.json?print=pretty "HTTP/1.1 200 OK"
[INFO   ] httpx: HTTP Request: GET https://hacker-news.firebaseio.com/v0/item/47583045.json?print=pretty "HTTP/1.1 200 OK"
[INFO   ] httpx: HTTP Request: GET https://hacker-news.firebaseio.com/v0/item/47582043.json?print=pretty "HTTP/1.1 200 OK"
[INFO   ] httpx: HTTP Request: GET https://hacker-news.firebaseio.com/v0/item/47581701.json?print=pretty "HTTP/1.1 200 OK"
```

---

## Other

_Miscellaneous logs that don't fall into the above categories._

**198 log entries captured** (showing up to 15 representative samples)

```
[INFO   ] samples.shared.model_client: AZURE_OPENAI_ENDPOINT found: https://vw-te-openai.openai.azure.com/
[INFO   ] samples.shared.model_client: AZURE_OPENAI_API_KEY not found - will use AAD authentication.
[DEBUG  ] asyncio: Using proactor: IocpProactor
[DEBUG  ] urllib3.connectionpool: Starting new HTTP connection (1): 169.254.169.254:80
[DEBUG  ] urllib3.connectionpool: Starting new HTTPS connection (1): westus-0.in.applicationinsights.azure.com:443
[DEBUG  ] urllib3.connectionpool: https://westus-0.in.applicationinsights.azure.com:443 "POST /v2.1/track HTTP/1.1" 200 None
[DEBUG  ] httpcore.http11: receive_response_body.complete
[DEBUG  ] httpcore.http11: response_closed.started
[DEBUG  ] httpcore.http11: response_closed.complete
[DEBUG  ] openai._base_client: HTTP Response: POST https://vw-te-openai.openai.azure.com/openai/deployments/gpt-4.1-mini/chat/completions?api-version=2024-10-21 "200 OK" Headers({'content-length': '1353', 'content-type': 'application/json', 'azureml-model-session': 'd20260302210219-55697c4f0a74',...
[DEBUG  ] openai._base_client: request_id: cd67ec4e-86ee-4d28-b887-f46d370cdc7f
  ... (183 more entries)
```

---

## Summary

| Category | Log entries | Levels |
|---|---|---|
| OpenTelemetry / Tracing | 10 | INFO |
| Azure Monitor Export | 9 | INFO |
| Agent Framework | 86 | DEBUG, INFO |
| Azure Identity / Auth | 25 | DEBUG, INFO |
| HTTP Requests (httpx) | 11 | INFO |
| Other | 198 | DEBUG, INFO |
| **Total** | **339** | |
