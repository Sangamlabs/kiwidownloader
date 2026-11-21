import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import httpx
from config import API_BASE, HEADERS, TEMP_DIR

logger = logging.getLogger(__name__)


class KiwiApiClient:
    def __init__(self, base_url: str = API_BASE, headers: dict = HEADERS):
        self.base_url = base_url
        self.headers = headers

    async def ping(self) -> float:
        """Measure API ping latency in milliseconds, returns -1.0 if unreachable"""
        start = asyncio.get_event_loop().time()
        endpoint = f"{self.base_url}/docs"
        timeout = httpx.Timeout(5.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                res = await client.get(endpoint)
                if res.status_code == 200:
                    return (asyncio.get_event_loop().time() - start) * 1000.0
                return -1.0
            except Exception:
                return -1.0

    async def get_media_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch media metadata from KiwiAPI (/v1/info)"""
        endpoint = f"{self.base_url}/v1/info"
        timeout = httpx.Timeout(60.0, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                res = await client.post(endpoint, json={"url": url}, headers=self.headers)
                if res.status_code == 200:
                    return res.json()
                logger.error(f"Info request failed ({res.status_code}): {res.text}")
                return None
            except Exception as e:
                logger.error(f"Error fetching media info: {e}")
                return None

    async def start_job(self, url: str, media_type: str = "video", quality: str = "1080p") -> Optional[str]:
        """Start a background download job (/v1/download) and return job_id"""
        endpoint = f"{self.base_url}/v1/download"
        payload = {"url": url, "type": media_type, "quality": quality}
        timeout = httpx.Timeout(60.0, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                res = await client.post(endpoint, json=payload, headers=self.headers)
                if res.status_code == 200:
                    data = res.json()
                    return data.get("id") or data.get("job_id")
                logger.error(f"Download job creation failed ({res.status_code}): {res.text}")
                return None
            except Exception as e:
                logger.error(f"Error starting download job: {e}")
                return None

    async def wait_for_job(self, job_id: str, timeout: int = 300, poll_interval: float = 0.5) -> bool:
        """Poll job status until done or timeout"""
        endpoint = f"{self.base_url}/v1/jobs/{job_id}"
        start_time = asyncio.get_event_loop().time()
        timeout_cfg = httpx.Timeout(20.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout_cfg) as client:
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    res = await client.get(endpoint, headers=self.headers)
                    if res.status_code == 200:
                        data = res.json()
                        status = data.get("status")
                        if status == "done":
                            return True
                        elif status == "failed":
                            err_msg = data.get("error", "Unknown error")
                            logger.error(f"Job {job_id} failed on backend: {err_msg}")
                            return False
                    await asyncio.sleep(poll_interval)
                except Exception as e:
                    logger.warning(f"Error polling job {job_id}: {e}")
                    await asyncio.sleep(poll_interval)
        return False

    async def download_file_to_disk(self, job_id: str) -> Optional[Path]:
        """Stream the prepared file from KiwiAPI into local temp storage"""
        endpoint = f"{self.base_url}/v1/files/{job_id}"
        target_path = TEMP_DIR / f"{job_id}.mp4"
        timeout = httpx.Timeout(300.0, connect=60.0, read=300.0, write=60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                async with client.stream("GET", endpoint, headers=self.headers) as response:
                    if response.status_code != 200:
                        logger.error(f"File download failed with status {response.status_code}")
                        return None
                    # Determine extension from content-disposition header if present
                    cd = response.headers.get("content-disposition", "")
                    if ".mp3" in cd.lower():
                        target_path = TEMP_DIR / f"{job_id}.mp3"
                    elif ".m4a" in cd.lower():
                        target_path = TEMP_DIR / f"{job_id}.m4a"
                    elif ".webm" in cd.lower():
                        target_path = TEMP_DIR / f"{job_id}.webm"
                    elif ".jpg" in cd.lower() or ".jpeg" in cd.lower():
                        target_path = TEMP_DIR / f"{job_id}.jpg"

                    with open(target_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=131072):
                            f.write(chunk)
                return target_path
            except Exception as e:
                logger.error(f"Failed to stream file {job_id}: {e}")
                return None

    async def recognize_audio(self, url: str) -> Optional[Dict[str, Any]]:
        """Identify background music via Shazam (/v1/recognize)"""
        endpoint = f"{self.base_url}/v1/recognize"
        timeout = httpx.Timeout(60.0, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                res = await client.post(endpoint, data={"url": url}, headers={"X-API-Key": HEADERS.get("X-API-Key", "")})
                if res.status_code == 200:
                    return res.json()
                logger.error(f"Recognition failed ({res.status_code}): {res.text}")
                return None
            except Exception as e:
                logger.error(f"Error recognizing audio: {e}")
                return None

    async def identify_anime(self, url: str) -> Optional[Dict[str, Any]]:
        """Identify Anime & Episode via /v1/identify-anime"""
        endpoint = f"{self.base_url}/v1/identify-anime"
        timeout = httpx.Timeout(45.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                res = await client.post(endpoint, json={"url": url}, headers={"X-API-Key": HEADERS.get("X-API-Key", "")})
                if res.status_code == 200:
                    return res.json()
                logger.error(f"Anime identification failed ({res.status_code}): {res.text}")
                return None
            except Exception as e:
                logger.error(f"Error identifying anime: {e}")
                return None
