from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render

from . import planner


def route(request):
    if request.method != "GET":
        return JsonResponse({"error": "use GET with ?start=...&finish=..."}, status=405)
    start, finish = request.GET.get("start", "").strip(), request.GET.get("finish", "").strip()
    if not start or not finish:
        return JsonResponse(
            {"error": "start and finish are required, e.g. ?start=Los Angeles, CA&finish=New York, NY (place name or lat,lon)"},
            status=400,
        )

    key = "".join(f"route:{start}|{finish}".lower().split())  # no spaces, django warns about them
    result = cache.get(key)
    if result is None:
        try:
            result = planner.plan(start, finish)
        except planner.ServiceDown as e:
            return JsonResponse({"error": str(e)}, status=502)
        except ValueError as e:
            return JsonResponse({"error": str(e)}, status=400)
        cache.set(key, result, 60 * 60)
    map_url = request.build_absolute_uri(f"/api/route/map/?{request.GET.urlencode()}")
    stops, route = result.pop("fuel_stops"), result.pop("route")  # summary first, long lists last
    return JsonResponse({**result, "map_url": map_url, "fuel_stops": stops, "route": route})


def map_page(request):
    """the map itself, draws /api/route/ for the same start and finish"""
    return render(request, "map.html")


def not_found(request, path=""):
    if path == "api/route":  # forgot the slash
        return redirect(f"/api/route/?{request.GET.urlencode()}")
    return JsonResponse({"error": f"/{path} does not exist, the only endpoint is /api/route/?start=...&finish=..."}, status=404)
