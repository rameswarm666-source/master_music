import os
import asyncio
import aiohttp
from urllib.parse import urlencode
from youtube_search import YoutubeSearch

# Naye env names jaan-bujhkar rakhe hain (DOWNLOAD_API_*) taaki Render par purane
# API_URL / API_KEY (nexor wale) galti se override na kar dein.
DOWNLOAD_API_URL = os.environ.get("DOWNLOAD_API_URL", "https://api.riteshyt.in")
DOWNLOAD_API_KEY = os.environ.get("DOWNLOAD_API_KEY", "riteshfreebc037f3c187a34610b8a04dc")

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def search_youtube(query: str):
    """YouTube pe search karta hai, pehla result deta hai (raw dict, library format)."""
    loop = asyncio.get_event_loop()

    def _search():
        results = YoutubeSearch(query, max_results=1).to_dict()
        return results[0] if results else None

    return await loop.run_in_executor(None, _search)


async def search_track(query: str):
    """search_youtube ka normalized wrapper — id/title/duration/thumbnail/url deta hai."""
    result = await search_youtube(query)
    if not result:
        return None

    thumbnails = result.get("thumbnails") or []
    video_id = result.get("id")

    return {
        "id": video_id,
        "title": result.get("title", "Unknown"),
        "duration": result.get("duration", ""),
        "thumbnail": thumbnails[0] if thumbnails else None,
        "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
    }


async def search_related_track(seed_title: str, exclude_ids=None):
    """Autoplay ke liye 'related' track dhoondta hai — seed track ke title se
    hi search karke, pehli aisi result jo already play na ho chuki ho (exclude_ids
    mein na ho) use karta hai. YouTube ka koi official 'related videos' API
    yahan use nahi ho raha (youtube_search library isse support nahi karti),
    isliye yeh best-effort approximation hai."""
    exclude_ids = exclude_ids or set()
    loop = asyncio.get_event_loop()

    def _search():
        results = YoutubeSearch(seed_title, max_results=6).to_dict()
        return results

    results = await loop.run_in_executor(None, _search)
    for r in results or []:
        vid = r.get("id")
        if vid and vid not in exclude_ids:
            thumbnails = r.get("thumbnails") or []
            return {
                "id": vid,
                "title": r.get("title", "Unknown"),
                "duration": r.get("duration", ""),
                "thumbnail": thumbnails[0] if thumbnails else None,
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
    return None


_URL_KEYS = (
    "download_url", "downloadUrl", "download", "stream_url", "streamUrl",
    "audio_url", "audioUrl", "url", "link", "file", "result", "data",
)


def _find_url(obj):
    """JSON response ke andar se pehla http(s) link dhoondta hai."""
    if isinstance(obj, str):
        return obj if obj.startswith(("http://", "https://")) else None
    if isinstance(obj, dict):
        for k in _URL_KEYS:
            if k in obj:
                found = _find_url(obj[k])
                if found:
                    return found
        for v in obj.values():
            found = _find_url(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = _find_url(v)
            if found:
                return found
    return None


async def get_stream_url(video_id: str) -> str:
    """
    riteshyt API se audio link banata hai:
    https://api.riteshyt.in/download?query=<VIDEO_ID>&dl_type=audio&api_key=<KEY>

    - Agar API seedha audio file/stream deta hai -> final URL (redirect ke baad)
      hi pytgcalls ko de dete hain.
    - Agar API JSON deta hai -> usme se download/stream link nikal lete hain.
    - "processing" jaisa status aaye to 3 baar retry karta hai.
    """
    params = urlencode({"query": video_id, "dl_type": "audio", "api_key": DOWNLOAD_API_KEY})
    api_url = f"{DOWNLOAD_API_URL.rstrip('/')}/download?{params}"

    last_err = "unknown error"
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    api_url,
                    timeout=aiohttp.ClientTimeout(total=40),
                    allow_redirects=True,
                ) as resp:
                    if resp.status >= 400:
                        last_err = f"API ne status {resp.status} diya"
                        await asyncio.sleep(2)
                        continue

                    ctype = (resp.headers.get("Content-Type") or "").lower()

                    # Seedha audio/binary stream -> body padhe bina URL return
                    if ctype.startswith(("audio/", "video/")) or "octet-stream" in ctype:
                        return str(resp.url)

                    body = await resp.text()
                    try:
                        data = __import__("json").loads(body)
                    except ValueError:
                        last_err = "API ka response samajh nahi aaya"
                        await asyncio.sleep(2)
                        continue

                    link = _find_url(data)
                    if link:
                        return link

                    last_err = f"API ne link nahi diya: {str(data)[:150]}"
                    await asyncio.sleep(3)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_err = f"API tak pahunch nahi paaye: {e}"
            await asyncio.sleep(2)

    raise Exception(last_err)
