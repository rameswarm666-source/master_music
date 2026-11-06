import os
import asyncio
import aiohttp
from youtube_search import YoutubeSearch

API_URL = os.environ.get("API_URL", "https://nexor-yt-pannl.lovable.app")
API_KEY = os.environ.get("API_KEY", "NEXOR_e4876563")

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


async def get_stream_url(video_id: str) -> str:
    """
    YukiAPI se direct audio stream URL banata hai:
    https://music.yukiapi.site/stream/{VIDEO_ID}?key=yuki_xxx

    Yeh endpoint khud hi streamable hai, isliye URL seedha pytgcalls ko de
    dete hain — koi extra download/redirect-follow ki zaroorat nahi. Bas ek
    halka HEAD check kar lete hain taaki invalid video_id turant pakda jaaye.
    """
    stream_url = f"{API_URL}/stream/{video_id}?key={API_KEY}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(
                stream_url,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True,
            ) as resp:
                if resp.status >= 400:
                    raise Exception(f"YukiAPI ne unexpected response diya: {resp.status}")
    except aiohttp.ClientError as e:
        raise Exception(f"YukiAPI tak pahunch nahi paaye: {e}")

    return stream_url
