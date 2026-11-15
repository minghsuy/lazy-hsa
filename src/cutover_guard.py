import httpx


def cutover(base_url: str) -> bool:
    with httpx.Client(base_url=base_url, timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        response = client.get("/cutover", timeout=3.0)
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict):
        return False
    return body["cutover"] is True
