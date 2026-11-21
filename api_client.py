import os
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import httpx
from config import API_BASE, HEADERS, TEMP_DIR

logger = logging.getLogger(__name__)


class KiwiApiClient:
    def __init__(self, base_url: str = API_BASE, headers: dict = HEADERS):
        # Public base URL (used for links sent to Telegram and users)
        self.public_base_url = base_url.rstrip("/")
        # Local internal loopback URL (used when bot runs on same server as KiwiAPI for ~1ms latency)
        self.internal_base_url = os.getenv("INTERNAL_API_BASE", "http://127.0.0.1:8000").rstrip("/")
        self.headers = headers
        self._active_base: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """Get or initialize persistent HTTPX client with connection pooling"""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0)
            timeout = httpx.Timeout(60.0, connect=10.0)
            self._client = httpx.AsyncClient(limits=limits, timeout=timeout)
        return self._client

    async def get_base_url(self) -> str:
        """Resolve whether to use ultra-fast local loopback or public API"""
        if self._active_base:
            return self._active_base

        # Check if local loopback 127.0.0.1:8000 is directly reachable
        try:
            client = await self.get_client()
            r = await client.get(f"{self.internal_base_url}/health", timeout=1.0)
            if r.status_code == 200:
                self._active_base = self.internal_base_url
                logger.info(f"Connected to KiwiAPI locally via {self.internal_base_url} (ultra-fast mode)")
                return self._active_base
        except Exception:
            pass

        self._active_base = self.public_base_url
        return self._active_base

    @property
    def base_url(self) -> str:
        """Public URL for streaming links sent to Telegram"""
        return self.public_base_url

    async def ping(self) -> float:
        """Measure API ping latency in milliseconds using /health endpoint"""
        start = asyncio.get_event_loop().time()
        base = await self.get_base_url()
        endpoint = f"{base}/health"
        client = await self.get_client()
        try:
            res = await client.get(endpoint, timeout=3.0)
            if res.status_code == 200:
                return (asyncio.get_event_loop().time() - start) * 1000.0
            return -1.0
        except Exception:
            return -1.0

    async def get_media_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch media metadata from KiwiAPI (/v1/info)"""
        base = await self.get_base_url()
        endpoint = f"{base}/v1/info"
        client = await self.get_client()
        try:
            res = await client.post(endpoint, json={"url": url}, headers=self.headers, timeout=60.0)
            if res.status_code == 200:
                return res.json()
            logger.error(f"Info request failed ({res.status_code}): {res.text}")
            return None
        except Exception as e:
            logger.error(f"Error fetching media info: {e}")
            return None

    async def start_job(self, url: str, media_type: str = "video", quality: str = "1080p") -> Optional[str]:
        """Start a background download job (/v1/download) and return job_id"""
        base = await self.get_base_url()
        endpoint = f"{base}/v1/download"
        payload = {"url": url, "type": media_type, "quality": quality}
        client = await self.get_client()
        try:
            res = await client.post(endpoint, json=payload, headers=self.headers, timeout=60.0)
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
        base = await self.get_base_url()
        endpoint = f"{base}/v1/jobs/{job_id}"
        start_time = asyncio.get_event_loop().time()
        client = await self.get_client()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                res = await client.get(endpoint, headers=self.headers, timeout=10.0)
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
        base = await self.get_base_url()
        endpoint = f"{base}/v1/files/{job_id}"
        target_path = TEMP_DIR / f"{job_id}.mp4"
        client = await self.get_client()

        try:
            async with client.stream("GET", endpoint, headers=self.headers, timeout=120.0) as response:
                if response.status_code != 200:
                    logger.error(f"File download failed with status {response.status_code}")
                    return None
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
        base = await self.get_base_url()
        endpoint = f"{base}/v1/recognize"
        client = await self.get_client()
        try:
            res = await client.post(endpoint, data={"url": url}, headers={"X-API-Key": HEADERS.get("X-API-Key", "")}, timeout=60.0)
            if res.status_code == 200:
                return res.json()
            logger.error(f"Recognition failed ({res.status_code}): {res.text}")
            return None
        except Exception as e:
            logger.error(f"Error recognizing audio: {e}")
            return None

    async def identify_anime(self, url: str) -> Optional[Dict[str, Any]]:
        """Identify Anime & Episode via /v1/identify-anime"""
        base = await self.get_base_url()
        endpoint = f"{base}/v1/identify-anime"
        client = await self.get_client()
        try:
            res = await client.post(endpoint, json={"url": url}, headers={"X-API-Key": HEADERS.get("X-API-Key", "")}, timeout=45.0)
            if res.status_code == 200:
                return res.json()
            logger.error(f"Anime identification failed ({res.status_code}): {res.text}")
            return None
        except Exception as e:
            logger.error(f"Error identifying anime: {e}")
            return None
